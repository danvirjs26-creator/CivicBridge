"""Deterministic Eligibility & Priority Engine (pure Python, zero LLM calls)."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

from app.models import EligibilityStatus, SchemeMatch, SchemeRecord, UserContext

DEFAULT_SCHEMES_PATH: Path = Path(__file__).resolve().parent / "data" / "schemes.json"

CORE_CRITERIA_COUNT: int = 4
WEIGHT_MATCH: float = 0.50
WEIGHT_BENEFIT: float = 0.30
WEIGHT_URGENCY: float = 0.20
GOAL_ALIGNMENT_BONUS: float = 5.0
MAX_SCORE: float = 100.0
ELIGIBILITY_CACHE_MAXSIZE: int = 512


def _normalize_token(value: str) -> str:
    """Normalize state, occupation, and category tokens for deterministic matching."""
    return value.strip().lower().replace("-", "_").replace(" ", "_")


@lru_cache(maxsize=4)
def load_schemes(path: Path = DEFAULT_SCHEMES_PATH) -> tuple[SchemeRecord, ...]:
    """Load and cache schemes from JSON into an immutable tuple of Pydantic models."""
    with path.open("r", encoding="utf-8") as fh:
        raw_items = json.load(fh)
    return tuple(SchemeRecord.model_validate(item) for item in raw_items)


def _check_criterion(
    condition: bool,
    matched_msg: str,
    unmet_msg: str,
    matched: list[str],
    unmet: list[str],
) -> None:
    """Record a single deterministic criterion outcome."""
    if condition:
        matched.append(matched_msg)
    else:
        unmet.append(unmet_msg)


def evaluate_scheme(user: UserContext, scheme: SchemeRecord) -> SchemeMatch:
    """Evaluate a single scheme deterministically against user context."""
    matched: list[str] = []
    unmet: list[str] = []

    # 1. Age check
    _check_criterion(
        scheme.min_age <= user.age <= scheme.max_age,
        f"Age {user.age} is within {scheme.min_age}-{scheme.max_age} years",
        f"Age {user.age} is outside required {scheme.min_age}-{scheme.max_age} years",
        matched,
        unmet,
    )

    # 2. State check
    normalized_states = {_normalize_token(s) for s in scheme.states}
    user_state_norm = _normalize_token(user.state)
    scope = "All India" if "all" in normalized_states else ", ".join(scheme.states)
    _check_criterion(
        "all" in normalized_states or user_state_norm in normalized_states,
        f"State '{user.state}' is covered ({scope})",
        f"Restricted to {', '.join(scheme.states)} (your state: {user.state})",
        matched,
        unmet,
    )

    # 3. Income check
    if scheme.max_income_inr is None:
        matched.append("No upper annual income cap")
    else:
        _check_criterion(
            user.annual_income_inr <= scheme.max_income_inr,
            f"Annual income INR {user.annual_income_inr:,} is within cap INR {scheme.max_income_inr:,}",
            f"Annual income INR {user.annual_income_inr:,} exceeds cap INR {scheme.max_income_inr:,}",
            matched,
            unmet,
        )

    # 4. Occupation check
    normalized_occupations = {_normalize_token(o) for o in scheme.occupations}
    user_occ_norm = _normalize_token(user.occupation)
    allowed_readable = ", ".join(o.replace("_", " ") for o in scheme.occupations)
    _check_criterion(
        "all" in normalized_occupations or user_occ_norm in normalized_occupations,
        f"Occupation '{user.occupation}' is eligible",
        f"Targeted at: {allowed_readable} (your occupation: {user.occupation})",
        matched,
        unmet,
    )

    unmet_count = len(unmet)
    if unmet_count == 0:
        status: EligibilityStatus = "eligible"
    elif unmet_count == 1:
        status = "near_match"
    else:
        status = "not_eligible"

    match_score = round((len(matched) / CORE_CRITERIA_COUNT) * MAX_SCORE, 1)
    base_priority = (
        WEIGHT_MATCH * match_score
        + WEIGHT_BENEFIT * scheme.benefit_score
        + WEIGHT_URGENCY * scheme.urgency_score
    )

    user_goal_norm = _normalize_token(user.category_goal)
    scheme_cat_norm = _normalize_token(scheme.category)
    goal_bonus = (
        GOAL_ALIGNMENT_BONUS
        if (user_goal_norm != "all" and user_goal_norm == scheme_cat_norm)
        else 0.0
    )
    if goal_bonus > 0:
        matched.append(f"Matches your selected goal ({scheme.category.replace('_', ' ')})")

    priority_score = round(min(MAX_SCORE, base_priority + goal_bonus), 1)

    return SchemeMatch(
        scheme=scheme,
        status=status,
        match_score=match_score,
        priority_score=priority_score,
        matched_criteria=matched,
        unmet_criteria=unmet,
    )


def _evaluate_schemes_iterable(
    user: UserContext, schemes: Iterable[SchemeRecord]
) -> tuple[list[SchemeMatch], list[SchemeMatch], list[SchemeMatch]]:
    """Evaluate and rank an arbitrary iterable of schemes into three status buckets."""
    eligible: list[SchemeMatch] = []
    near_match: list[SchemeMatch] = []
    not_eligible: list[SchemeMatch] = []

    for scheme in schemes:
        result = evaluate_scheme(user, scheme)
        if result.status == "eligible":
            eligible.append(result)
        elif result.status == "near_match":
            near_match.append(result)
        else:
            not_eligible.append(result)

    def _sort_key(item: SchemeMatch) -> tuple[float, float, str]:
        return (-item.priority_score, -item.match_score, item.scheme.name)

    eligible.sort(key=_sort_key)
    near_match.sort(key=_sort_key)
    not_eligible.sort(key=_sort_key)

    return eligible, near_match, not_eligible


@lru_cache(maxsize=ELIGIBILITY_CACHE_MAXSIZE)
def _evaluate_default_cached(
    age: int,
    state_norm: str,
    occupation_norm: str,
    annual_income_inr: int,
    category_goal_norm: str,
) -> tuple[tuple[SchemeMatch, ...], tuple[SchemeMatch, ...], tuple[SchemeMatch, ...]]:
    """Cache deterministic evaluation results for the default scheme catalog."""
    user = UserContext(
        age=age,
        state=state_norm,
        occupation=occupation_norm,
        annual_income_inr=annual_income_inr,
        category_goal=category_goal_norm,
    )
    eligible, near_match, not_eligible = _evaluate_schemes_iterable(user, load_schemes())
    return tuple(eligible), tuple(near_match), tuple(not_eligible)


def evaluate_all_schemes(
    user: UserContext, schemes: Optional[Iterable[SchemeRecord]] = None
) -> tuple[list[SchemeMatch], list[SchemeMatch], list[SchemeMatch]]:
    """Evaluate and rank all schemes into Eligible, Near-Match, and Not Eligible buckets."""
    if schemes is None:
        eligible_t, near_t, not_eligible_t = _evaluate_default_cached(
            user.age,
            _normalize_token(user.state),
            _normalize_token(user.occupation),
            user.annual_income_inr,
            _normalize_token(user.category_goal),
        )
        return list(eligible_t), list(near_t), list(not_eligible_t)
    return _evaluate_schemes_iterable(user, schemes)


def clear_engine_caches() -> None:
    """Clear in-memory LRU caches (useful for testing)."""
    load_schemes.cache_clear()
    _evaluate_default_cached.cache_clear()
