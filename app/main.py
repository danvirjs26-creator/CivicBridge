"""FastAPI application entrypoint for CivicBridge."""

import logging
import os
from pathlib import Path
from typing import Awaitable, Callable

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.ai_service import generate_action_guide
from app.engine import evaluate_all_schemes, load_schemes
from app.models import EvaluateResponse, UserContext
from app.security import PromptInjectionError, validate_and_sanitize_question

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR: Path = Path(__file__).resolve().parent.parent
STATIC_DIR: Path = BASE_DIR / "static"
STATIC_CACHE_MAX_AGE_SECONDS: int = 3600
GZIP_MINIMUM_SIZE_BYTES: int = 500


def create_app() -> FastAPI:
    """Construct and configure the FastAPI application with security, compression, and routes."""
    application = FastAPI(
        title="CivicBridge",
        description="Context-Aware AI Public Scheme & Benefit Navigator",
        version="1.0.0",
    )

    # Warm the LRU-cached scheme catalog once at app initialization
    schemes = load_schemes()

    allowed_origins_raw = os.getenv("ALLOWED_ORIGINS", "*")
    allowed_origins = [
        origin.strip() for origin in allowed_origins_raw.split(",") if origin.strip()
    ]
    application.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    application.add_middleware(GZipMiddleware, minimum_size=GZIP_MINIMUM_SIZE_BYTES)

    @application.middleware("http")
    async def add_security_and_cache_headers(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Attach strict HTTP security headers and static asset Cache-Control headers."""
        response = await call_next(request)
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
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = f"public, max-age={STATIC_CACHE_MAX_AGE_SECONDS}"
        return response

    @application.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Return structured 422 details for invalid request payloads."""
        logger.warning("Validation error on %s: %s", request.url.path, exc.errors())
        return JSONResponse(
            status_code=422,
            content={"detail": "Invalid input parameters.", "errors": exc.errors()},
        )

    @application.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        """Log unexpected errors without leaking internal details to clients."""
        logger.exception("Unhandled error on %s: %s", request.url.path, exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error. Please try again later."},
        )

    @application.get("/health")
    def health_check() -> dict[str, str | int]:
        """Return service health status and loaded scheme count."""
        return {
            "status": "ok",
            "service": "civicbridge",
            "schemes_loaded": len(schemes),
        }

    @application.get("/api/schemes")
    def list_schemes() -> dict[str, int | list[dict]]:
        """Return the full catalog of verified public schemes."""
        return {
            "count": len(schemes),
            "schemes": [s.model_dump() for s in schemes],
        }

    @application.post("/api/evaluate", response_model=EvaluateResponse)
    async def evaluate_eligibility(user: UserContext) -> EvaluateResponse:
        """Evaluate user eligibility deterministically and generate a grounded action guide."""
        try:
            sanitized_question, pii_redacted = validate_and_sanitize_question(user.question)
        except PromptInjectionError as exc:
            logger.warning("Blocked prompt-injection attempt: %s", exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        warnings: list[str] = []
        if pii_redacted:
            warnings.append(
                "Sensitive personal identifiers (e.g., Aadhaar, PAN, phone, or email) were automatically redacted before AI processing."
            )

        eligible, near_match, not_eligible = evaluate_all_schemes(user)

        ai_guide = await generate_action_guide(
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
            total_evaluated=len(schemes),
            ai_guide=ai_guide,
            sanitized_question=sanitized_question,
            warnings=warnings,
        )

    if STATIC_DIR.exists():
        application.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

        @application.get("/", include_in_schema=False)
        def serve_index() -> FileResponse:
            """Serve the accessible single-page frontend."""
            return FileResponse(str(STATIC_DIR / "index.html"))

    return application


app: FastAPI = create_app()
