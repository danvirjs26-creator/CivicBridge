"""Unit tests for the deterministic Eligibility & Priority Engine."""

from app.engine import (
    _evaluate_default_cached,
    clear_engine_caches,
    evaluate_all_schemes,
    evaluate_scheme,
    load_schemes,
)
from app.models import SchemeRecord, UserContext


def test_load_schemes_contains_15_valid_records():
    schemes = load_schemes()
    assert len(schemes) == 15
    categories = {s.category for s in schemes}
    assert {"farmer", "student", "welfare", "women", "msme", "senior_citizen"} <= categories


def test_student_exact_match_and_near_match():
    schemes = load_schemes()
    user = UserContext(
        age=20,
        state="Karnataka",
        occupation="student",
        annual_income_inr=180000,
        category_goal="student",
    )
    eligible, near_match, not_eligible = evaluate_all_schemes(user, schemes)
    eligible_ids = {m.scheme.id for m in eligible}

    assert "nsp-post-matric-scholarship" in eligible_ids
    assert "pm-yasasvi-scholarship" in eligible_ids
    assert "pm-vidyalaxmi-education" in eligible_ids
    assert "pm-jan-arogya-yojana" in eligible_ids
    # Senior pension requires age >= 60 AND income <= 150000 -> 2 unmet criteria -> not_eligible
    not_eligible_ids = {m.scheme.id for m in not_eligible}
    assert "ignoaps-senior-pension" in not_eligible_ids


def test_near_match_when_exactly_one_criterion_fails():
    scheme = SchemeRecord(
        id="test-scheme",
        name="Test Farmer Scheme",
        category="farmer",
        states=["Maharashtra"],
        min_age=18,
        max_age=60,
        max_income_inr=200000,
        occupations=["farmer"],
        benefit_summary="Test benefit",
        benefit_score=80,
        urgency_score=70,
        documents_required=["Aadhaar"],
        official_portal="https://example.gov.in/",
    )
    # Only income fails (250000 > 200000)
    user = UserContext(
        age=35,
        state="Maharashtra",
        occupation="farmer",
        annual_income_inr=250000,
        category_goal="farmer",
    )
    result = evaluate_scheme(user, scheme)
    assert result.status == "near_match"
    assert result.match_score == 75.0
    assert len(result.unmet_criteria) == 1
    assert "exceeds cap" in result.unmet_criteria[0]


def test_priority_ranking_orders_goal_aligned_and_high_priority_first():
    schemes = load_schemes()
    user = UserContext(
        age=42,
        state="Uttar Pradesh",
        occupation="farmer",
        annual_income_inr=160000,
        category_goal="farmer",
    )
    eligible, _, _ = evaluate_all_schemes(user, schemes)
    assert len(eligible) >= 3
    scores = [m.priority_score for m in eligible]
    assert scores == sorted(scores, reverse=True)
    # Top eligible schemes should include farmer schemes due to category_goal bonus
    top_categories = {m.scheme.category for m in eligible[:3]}
    assert "farmer" in top_categories


def test_state_specific_scheme_only_eligible_in_target_state():
    schemes = load_schemes()
    ladli = next(s for s in schemes if s.id == "ladki-bahin-maharashtra")

    mh_user = UserContext(
        age=28,
        state="Maharashtra",
        occupation="homemaker",
        annual_income_inr=200000,
        category_goal="women",
    )
    ka_user = UserContext(
        age=28,
        state="Karnataka",
        occupation="homemaker",
        annual_income_inr=200000,
        category_goal="women",
    )

    assert evaluate_scheme(mh_user, ladli).status == "eligible"
    ka_res = evaluate_scheme(ka_user, ladli)
    assert ka_res.status == "near_match"
    assert any("Maharashtra" in reason for reason in ka_res.unmet_criteria)


def test_boundary_age_and_null_income_cap():
    schemes = load_schemes()
    kcc = next(s for s in schemes if s.id == "kisan-credit-card")
    high_income_farmer = UserContext(
        age=18,
        state="Punjab",
        occupation="farmer",
        annual_income_inr=5000000,
        category_goal="farmer",
    )
    res = evaluate_scheme(high_income_farmer, kcc)
    assert res.status == "eligible"
    assert "No upper annual income cap" in res.matched_criteria


def test_engine_lru_caching_hits_on_repeated_calls():
    clear_engine_caches()
    first = load_schemes()
    second = load_schemes()
    assert first is second
    assert load_schemes.cache_info().hits >= 1

    user_a = UserContext(
        age=22,
        state="Karnataka",
        occupation="student",
        annual_income_inr=150000,
        category_goal="student",
    )
    user_b = UserContext(
        age=22,
        state="  karnataka ",
        occupation="Student",
        annual_income_inr=150000,
        category_goal="STUDENT",
    )
    res_a = evaluate_all_schemes(user_a)
    res_b = evaluate_all_schemes(user_b)
    assert res_a == res_b
    assert _evaluate_default_cached.cache_info().hits >= 1
