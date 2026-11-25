"""Grounded AI guidance service using google-genai with async timeout and fallback."""

import asyncio
import json
import logging
import os
from typing import Optional

from google import genai
from google.genai import types

from app.models import ActionStep, AIGuideResponse, SchemeMatch, UserContext

logger = logging.getLogger(__name__)

DEFAULT_GEMINI_MODEL: str = "gemini-3.5-flash-lite"
DEFAULT_AI_TIMEOUT_SECONDS: float = 8.0
MAX_SCHEMES_FOR_AI: int = 5
MAX_FALLBACK_STEPS: int = 4


def _build_deterministic_fallback(
    user: UserContext,
    top_schemes: list[SchemeMatch],
    sanitized_question: Optional[str],
    pii_redacted: bool,
    model_name: str,
) -> AIGuideResponse:
    """Generate a structured, plain-language guide without calling an external LLM."""
    eligible = [m for m in top_schemes if m.status == "eligible"]
    near_matches = [m for m in top_schemes if m.status == "near_match"]

    if not top_schemes:
        return AIGuideResponse(
            summary=(
                "No schemes matched your current profile directly. Review the criteria on "
                "all evaluated schemes or adjust your category goal to explore broader options."
            ),
            steps=[
                ActionStep(
                    step_number=1,
                    title="Verify profile details",
                    description="Double-check your state, occupation, and annual household income.",
                ),
                ActionStep(
                    step_number=2,
                    title="Explore national welfare portals",
                    description="Visit myscheme.gov.in to check newly added central and state programs.",
                ),
            ],
            document_checklist=["Aadhaar Card", "Income Certificate", "Bank Account Passbook"],
            source="deterministic_fallback",
            model_used=model_name,
            pii_redacted=pii_redacted,
        )

    lead_names = ", ".join(m.scheme.name for m in (eligible[:2] or near_matches[:2]))
    summary = (
        f"Based on your verified profile (Age {user.age}, {user.state}, {user.occupation}), "
        f"your highest-priority options are {lead_names}."
    )
    if sanitized_question:
        summary += f" Regarding your question ('{sanitized_question}'), follow the verified steps below."

    steps: list[ActionStep] = []
    seen_docs: dict[str, None] = {}

    for idx, match in enumerate(top_schemes[:MAX_FALLBACK_STEPS], start=1):
        for doc in match.scheme.documents_required:
            seen_docs.setdefault(doc, None)

        if match.status == "eligible":
            desc = (
                f"You meet all core criteria. Prepare {', '.join(match.scheme.documents_required[:3])} "
                f"and apply via {match.scheme.official_portal}."
            )
            title = f"Apply for {match.scheme.name}"
        else:
            gap = match.unmet_criteria[0] if match.unmet_criteria else "one eligibility criterion"
            desc = (
                f"Near match (1 criterion away: {gap}). Verify if an exemption or updated "
                f"certificate applies on {match.scheme.official_portal}."
            )
            title = f"Check eligibility gap for {match.scheme.name}"

        steps.append(
            ActionStep(
                step_number=idx,
                title=title,
                description=desc,
                scheme_id=match.scheme.id,
            )
        )

    return AIGuideResponse(
        summary=summary,
        steps=steps,
        document_checklist=list(seen_docs.keys()),
        source="deterministic_fallback",
        model_used=model_name,
        pii_redacted=pii_redacted,
    )


def _build_prompt(
    user: UserContext,
    top_schemes: list[SchemeMatch],
    sanitized_question: Optional[str],
) -> str:
    """Create a strictly grounded prompt containing only verified scheme data."""
    verified_payload = [
        {
            "id": m.scheme.id,
            "name": m.scheme.name,
            "status": m.status,
            "priority_score": m.priority_score,
            "matched_criteria": m.matched_criteria,
            "unmet_criteria": m.unmet_criteria,
            "benefit_summary": m.scheme.benefit_summary,
            "documents_required": m.scheme.documents_required,
            "official_portal": m.scheme.official_portal,
        }
        for m in top_schemes
    ]

    question_block = sanitized_question or "Provide a clear step-by-step application plan."

    return (
        "You are CivicBridge, an accurate Indian public scheme navigator.\n"
        "STRICT GROUNDING RULES:\n"
        "1. ONLY reference the verified schemes provided in the JSON below. Never invent schemes, benefits, or URLs.\n"
        "2. Use plain, accessible language.\n"
        "3. Return valid JSON matching this exact schema:\n"
        '{"summary": str, "steps": [{"step_number": int, "title": str, "description": str, "scheme_id": str|null}], "document_checklist": [str]}\n\n'
        f"Citizen Profile: Age={user.age}, State={user.state}, Occupation={user.occupation}, "
        f"Annual Income INR={user.annual_income_inr}, Goal={user.category_goal}\n"
        f"Sanitized Question: {question_block}\n\n"
        f"Verified Schemes:\n{json.dumps(verified_payload, ensure_ascii=False)}"
    )


def _call_gemini_sync(api_key: str, model_name: str, prompt: str) -> str:
    """Invoke google-genai synchronously (intended for threadpool execution)."""
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.2,
            response_mime_type="application/json",
        ),
    )
    return (response.text or "").strip()


def _get_timeout_seconds() -> float:
    """Parse AI timeout from environment, falling back to default on invalid values."""
    raw = os.getenv("GEMINI_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return DEFAULT_AI_TIMEOUT_SECONDS
    try:
        parsed = float(raw)
        return parsed if parsed > 0 else DEFAULT_AI_TIMEOUT_SECONDS
    except ValueError:
        return DEFAULT_AI_TIMEOUT_SECONDS


async def generate_action_guide(
    user: UserContext,
    eligible_schemes: list[SchemeMatch],
    near_match_schemes: list[SchemeMatch],
    sanitized_question: Optional[str] = None,
    pii_redacted: bool = False,
) -> AIGuideResponse:
    """Generate a personalized action guide asynchronously with strict timeout and fallback."""
    model_name = os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip() or DEFAULT_GEMINI_MODEL
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    top_schemes = (eligible_schemes + near_match_schemes)[:MAX_SCHEMES_FOR_AI]

    if not api_key or not top_schemes:
        return _build_deterministic_fallback(
            user=user,
            top_schemes=top_schemes,
            sanitized_question=sanitized_question,
            pii_redacted=pii_redacted,
            model_name=model_name,
        )

    prompt = _build_prompt(user, top_schemes, sanitized_question)
    timeout_seconds = _get_timeout_seconds()

    try:
        raw_text = await asyncio.wait_for(
            asyncio.to_thread(_call_gemini_sync, api_key, model_name, prompt),
            timeout=timeout_seconds,
        )
        parsed = json.loads(raw_text)

        steps = [
            ActionStep(
                step_number=int(s.get("step_number", idx)),
                title=str(s["title"]),
                description=str(s["description"]),
                scheme_id=s.get("scheme_id"),
            )
            for idx, s in enumerate(parsed.get("steps", []), start=1)
        ]

        return AIGuideResponse(
            summary=str(parsed["summary"]),
            steps=steps,
            document_checklist=[str(doc) for doc in parsed.get("document_checklist", [])],
            source="gemini",
            model_used=model_name,
            pii_redacted=pii_redacted,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Gemini guide generation timed out after %.1fs; using deterministic fallback.",
            timeout_seconds,
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        logger.warning("Gemini response parsing failed (%s); using deterministic fallback.", exc)
    except Exception as exc:  # noqa: BLE001 — intentional graceful degradation for external SDK errors
        logger.warning("Gemini guide generation failed (%s); using deterministic fallback.", exc)

    return _build_deterministic_fallback(
        user=user,
        top_schemes=top_schemes,
        sanitized_question=sanitized_question,
        pii_redacted=pii_redacted,
        model_name=model_name,
    )
