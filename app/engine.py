"""Deterministic Eligibility & Priority Engine (pure Python, zero LLM calls)."""

import json
from pathlib import Path
from typing import Iterable

from app.models import EligibilityStatus, SchemeMatch, SchemeRecord, UserContext

DEFAULT_SCHEMES_PATH = Path(__file__).resolve().parent / "data" / "schemes.json"


def _normalize_token(value: str) -> str:
    """Normalize state, occupation, and category tokens for deterministic matching."""
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def load_schemes(path: Path = DEFAULT_SCHEMES_PATH) -> list[SchemeRecord]:
    """Load and validate schemes from JSON into Pydantic models."""
    with path.open("r", encoding="utf-8") as fh:
        raw_items = json.load(fh)
    return [SchemeRecord.model_validate(item) for item in raw_items]


def evaluate_scheme(user: UserContext, scheme: SchemeRecord) -> SchemeMatch:
    """Evaluate a single scheme deterministically against user context."""
    matched: list[str] = []
    unmet: list[str] = []

    # 1. Age check
    if scheme.min_age <= user.age <= scheme.max_age:
        matched.append(f"Age {user.age} is within {scheme.min_age}-{scheme.max_age} years")
    else:
        unmet.append(f"Age {user.age} is outside required {scheme.min_age}-{scheme.max_age} years")

    # 2. State check
    normalized_states = {_normalize_token(s) for s in scheme.states}
    user_state_norm = _normalize_token(user.state)
    if "all" in normalized_states or user_state_norm in normalized_states:
        scope = "All India" if "all" in normalized_states else ", ".join(scheme.states)
        matched.append(f"State '{user.state}' is covered ({scope})")
    else:
        unmet.append(f"Restricted to {', '.join(scheme.states)} (your state: {user.state})")

    # 3. Income check
    if scheme.max_income_inr is None:
        matched.append("No upper annual income cap")
    elif user.annual_income_inr <= scheme.max_income_inr:
        matched.append(
            f"Annual income INR {user.annual_income_inr:,} is within cap INR {scheme.max_income_inr:,}"
        )
    else:
        unmet.append(
            f"Annual income INR {user.annual_income_inr:,} exceeds cap INR {scheme.max_income_inr:,}"
        )

    # 4. Occupation check
    normalized_occupations = {_normalize_token(o) for o in scheme.occupations}
    user_occ_norm = _normalize_token(user.occupation)
    if "all" in normalized_occupations or user_occ_norm in normalized_occupations:
        matched.append(f"Occupation '{user.occupation}' is eligible")
    else:
        allowed_readable = ", ".join(o.replace("_", " ") for o in scheme.occupations)
        unmet.append(f"Targeted at: {allowed_readable} (your occupation: {user.occupation})")

    # Deterministic status classification
    unmet_count = len(unmet)
    if unmet_count == 0:
        status: EligibilityStatus = "eligible"
    elif unmet_count == 1:
        status = "near_match"
    else:
        status = "not_eligible"

    # Match score out of 100 (4 equal core criteria)
    match_score = round((len(matched) / 4.0) * 100.0, 1)

    # Transparent priority score combining match confidence, benefit value, and urgency
    base_priority = (
        0.50 * match_score
        + 0.30 * scheme.benefit_score
        + 0.20 * scheme.urgency_score
    )

    # Optional category/goal alignment boost
    user_goal_norm = _normalize_token(user.category_goal)
    scheme_cat_norm = _normalize_token(scheme.category)
    goal_bonus = 5.0 if (user_goal_norm != "all" and user_goal_norm == scheme_cat_norm) else 0.0
    if goal_bonus > 0:
        matched.append(f"Matches your selected goal ({scheme.category.replace('_', ' ')})")

    priority_score = round(min(100.0, base_priority + goal_bonus), 1)

    return SchemeMatch(
        scheme=scheme,
        status=status,
        match_score=match_score,
        priority_score=priority_score,
        matched_criteria=matched,
        unmet_criteria=unmet,
    )


def evaluate_all_schemes(
    user: UserContext, schemes: Iterable[SchemeRecord]
) -> tuple[list[SchemeMatch], list[SchemeMatch], list[SchemeMatch]]:
    """Evaluate and rank all schemes into Eligible, Near-Match, and Not Eligible buckets."""
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

    sort_key = lambda item: (-item.priority_score, -item.match_score, item.scheme.name)
    eligible.sort(key=sort_key)
    near_match.sort(key=sort_key)
    not_eligible.sort(key=sort_key)

    return eligible, near_match, not_eligible
