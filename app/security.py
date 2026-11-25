"""Input sanitization, prompt-injection detection, and PII redaction."""

import re
from typing import Tuple


class PromptInjectionError(ValueError):
    """Raised when user input contains suspected prompt-injection instructions."""


# Compiled PII patterns (ordered from most specific to general)
_AADHAAR_PATTERN = re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b")
_PAN_PATTERN = re.compile(r"\b[A-Za-z]{5}\d{4}[A-Za-z]\b")
_EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+91[\s-]?|0)?[6-9]\d{9}(?!\d)")

# Prompt-injection / jailbreak patterns
_INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "instruction_override",
        re.compile(
            r"\b(?:ignore|disregard|forget|override)\s+(?:all\s+|any\s+|previous\s+|prior\s+|above\s+)*(?:instructions|rules|prompts|constraints)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "system_prompt_probe",
        re.compile(
            r"\b(?:reveal|show|print|leak|dump|output)\s+(?:your\s+|the\s+)?(?:system\s+prompt|hidden\s+instructions|developer\s+message)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "role_hijack",
        re.compile(
            r"\b(?:you\s+are\s+now|act\s+as\s+(?:an?\s+)?unrestricted|jailbreak|dan\s+mode|bypass\s+(?:security|safety|filter|rules))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "delimiter_injection",
        re.compile(r"(?:<\s*/?\s*system\s*>|###\s*system\s*:|role\s*:\s*system)", re.IGNORECASE),
    ),
    (
        "script_injection",
        re.compile(r"<\s*script\b|javascript\s*:", re.IGNORECASE),
    ),
]

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WHITESPACE_RE = re.compile(r"\s+")


def sanitize_text(text: str, max_length: int = 1000) -> str:
    """Remove control characters, normalize whitespace, and enforce length limits."""
    if not text:
        return ""
    cleaned = _CONTROL_CHARS_RE.sub("", text)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
    return cleaned[:max_length]


def detect_prompt_injection(text: str) -> list[str]:
    """Return a list of matched prompt-injection rule names, or empty list if clean."""
    if not text:
        return []
    matched: list[str] = []
    for label, pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            matched.append(label)
    return matched


def redact_pii(text: str) -> Tuple[str, bool]:
    """Mask Aadhaar, PAN, Indian phone numbers, and email addresses before LLM calls."""
    if not text:
        return "", False

    redacted = text
    redacted, n_aadhaar = _AADHAAR_PATTERN.subn("[REDACTED_AADHAAR]", redacted)
    redacted, n_pan = _PAN_PATTERN.subn("[REDACTED_PAN]", redacted)
    redacted, n_email = _EMAIL_PATTERN.subn("[REDACTED_EMAIL]", redacted)
    redacted, n_phone = _PHONE_PATTERN.subn("[REDACTED_PHONE]", redacted)

    was_redacted = (n_aadhaar + n_pan + n_email + n_phone) > 0
    return redacted, was_redacted


def validate_and_sanitize_question(question: str | None) -> tuple[str | None, bool]:
    """Sanitize user question, block prompt injection, and redact PII."""
    if question is None:
        return None, False

    cleaned = sanitize_text(question)
    if not cleaned:
        return None, False

    injection_hits = detect_prompt_injection(cleaned)
    if injection_hits:
        raise PromptInjectionError(
            "Input blocked: potential prompt-injection or unsafe instruction detected."
        )

    redacted, was_redacted = redact_pii(cleaned)
    return redacted, was_redacted
