"""FastAPI application entrypoint for CivicBridge."""

import os
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.ai_service import generate_action_guide
from app.engine import evaluate_all_schemes, load_schemes
from app.models import EvaluateResponse, SchemeRecord, UserContext
from app.security import PromptInjectionError, validate_and_sanitize_question

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

SCHEMES: list[SchemeRecord] = load_schemes()


def create_app() -> FastAPI:
    """Construct and configure the FastAPI application."""
    application = FastAPI(
        title="CivicBridge",
        description="Context-Aware AI Public Scheme & Benefit Navigator",
        version="1.0.0",
    )

    allowed_origins_raw = os.getenv("ALLOWED_ORIGINS", "*")
    allowed_origins = [origin.strip() for origin in allowed_origins_raw.split(",") if origin.strip()]
    application.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @application.middleware("http")
    async def add_security_headers(request: Request, call_next: Callable) -> Response:
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        return response

    @application.get("/health")
    def health_check() -> dict:
        return {
            "status": "ok",
            "service": "civicbridge",
            "schemes_loaded": len(SCHEMES),
        }

    @application.get("/api/schemes")
    def list_schemes() -> dict:
        return {
            "count": len(SCHEMES),
            "schemes": [s.model_dump() for s in SCHEMES],
        }

    @application.post("/api/evaluate", response_model=EvaluateResponse)
    def evaluate_eligibility(user: UserContext) -> EvaluateResponse:
        try:
            sanitized_question, pii_redacted = validate_and_sanitize_question(user.question)
        except PromptInjectionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        warnings: list[str] = []
        if pii_redacted:
            warnings.append(
                "Sensitive personal identifiers (e.g., Aadhaar, PAN, phone, or email) were automatically redacted before AI processing."
            )

        eligible, near_match, not_eligible = evaluate_all_schemes(user, SCHEMES)

        ai_guide = generate_action_guide(
            user=user,
            eligible_schemes=eligible,
            near_match_schemes=near_match,
            sanitized_question=sanitized_question,
            pii_redacted=pii_redacted,
        )

        return EvaluateResponse(
            eligible_schemes=eligible,
            near_match_schemes=near_match,
            not_eligible_schemes=not_eligible,
            total_evaluated=len(SCHEMES),
            ai_guide=ai_guide,
            sanitized_question=sanitized_question,
            warnings=warnings,
        )

    if STATIC_DIR.exists():
        application.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

        @application.get("/", include_in_schema=False)
        def serve_index() -> FileResponse:
            return FileResponse(str(STATIC_DIR / "index.html"))

    return application


app = create_app()
