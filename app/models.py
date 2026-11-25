"""Strict Pydantic v2 schemas for CivicBridge."""

from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


EligibilityStatus = Literal["eligible", "near_match", "not_eligible"]


class UserContext(BaseModel):
    """Validated citizen profile and optional question submitted by the user."""

    model_config = ConfigDict(str_strip_whitespace=True)

    age: int = Field(..., ge=0, le=120, description="Applicant age in years")
    state: str = Field(..., min_length=2, max_length=60, description="Indian State or UT")
    occupation: str = Field(..., min_length=2, max_length=60, description="Primary occupation")
    annual_income_inr: int = Field(..., ge=0, le=100_000_000, description="Annual household income in INR")
    category_goal: str = Field(
        default="all",
        min_length=2,
        max_length=40,
        description="Target benefit category or goal",
    )
    question: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Optional plain-language question about applying",
    )

    @field_validator("question", mode="before")
    @classmethod
    def empty_question_to_none(cls, value: Optional[str]) -> Optional[str]:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class SchemeRecord(BaseModel):
    """Structured public welfare scheme record."""

    id: str
    name: str
    category: str
    states: list[str]
    min_age: int = Field(..., ge=0)
    max_age: int = Field(..., ge=0)
    max_income_inr: Optional[int] = Field(default=None, ge=0)
    occupations: list[str]
    benefit_summary: str
    benefit_score: float = Field(..., ge=0, le=100)
    urgency_score: float = Field(..., ge=0, le=100)
    documents_required: list[str]
    official_portal: str


class SchemeMatch(BaseModel):
    """Deterministic eligibility evaluation result for a single scheme."""

    scheme: SchemeRecord
    status: EligibilityStatus
    match_score: float = Field(..., ge=0, le=100)
    priority_score: float = Field(..., ge=0, le=100)
    matched_criteria: list[str]
    unmet_criteria: list[str]


class ActionStep(BaseModel):
    """Single actionable step in the personalized application guide."""

    step_number: int = Field(..., ge=1)
    title: str
    description: str
    scheme_id: Optional[str] = None


class AIGuideResponse(BaseModel):
    """Grounded plain-language application guide and checklist."""

    summary: str
    steps: list[ActionStep]
    document_checklist: list[str]
    source: Literal["gemini", "deterministic_fallback"]
    model_used: str
    pii_redacted: bool = False


class EvaluateResponse(BaseModel):
    """Full API response combining deterministic matches and grounded AI guidance."""

    eligible_schemes: list[SchemeMatch]
    near_match_schemes: list[SchemeMatch]
    not_eligible_schemes: list[SchemeMatch]
    total_evaluated: int
    ai_guide: Optional[AIGuideResponse] = None
    sanitized_question: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
