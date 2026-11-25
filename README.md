# CivicBridge — Context-Aware AI Public Scheme & Benefit Navigator

## 1. Chosen Vertical
**CivicTech / Open Innovation — Public Scheme & Benefit Navigator**

Millions of citizens miss out on government scholarships, farmer subsidies, healthcare coverage, MSME credit, and social security pensions because eligibility rules are fragmented across portals and written in dense bureaucratic language. **CivicBridge** bridges that gap by combining deterministic rule verification with plain-language, grounded AI guidance.

---

## 2. Approach and Logic
**Hybrid Deterministic Eligibility Engine + Grounded LLM**

CivicBridge separates **eligibility truth** from **language generation** so an LLM can never hallucinate eligibility or invent fake schemes:

1. **Deterministic Eligibility & Priority Engine (`app/engine.py`):**
   - Pure Python, zero LLM calls, 100% unit-testable.
   - Evaluates each scheme in `app/data/schemes.json` across four core criteria: **Age**, **State/UT**, **Annual Income (INR)**, and **Occupation**.
   - Classifies every scheme into:
     - **Eligible** (`0` unmet criteria)
     - **Near-Match** (`1` unmet criterion)
     - **Not Eligible** (`2+` unmet criteria)
   - Computes a transparent **Priority Score**:
     $$\text{Priority} = \min\left(100,\; 0.50 \cdot \text{MatchScore} + 0.30 \cdot \text{BenefitScore} + 0.20 \cdot \text{UrgencyScore} + \text{GoalBonus}\right)$$
   - Returns structured `matched_criteria` and `unmet_criteria` explanations for every scheme.

2. **Grounded AI Action Guide (`app/ai_service.py`):**
   - Receives **only** the sanitized, PII-redacted user question and the top verified schemes from `engine.py`.
   - Uses the `google-genai` SDK (`gemini-3.5-flash-lite` by default, configurable via `GEMINI_MODEL`) to generate a plain-language summary, step-by-step action plan, and document checklist.
   - Automatically falls back to a deterministic plain-language guide if `GEMINI_API_KEY` is unset or the API call fails.

---

## 3. How the Solution Works

### Architecture
- `app/main.py` — FastAPI server, security headers middleware, CORS, `/health`, `/api/schemes`, `/api/evaluate`, and static UI serving.
- `app/models.py` — Strict Pydantic v2 schemas for requests, schemes, matches, and AI responses.
- `app/engine.py` — Deterministic rule evaluation and priority ranking.
- `app/security.py` — Control-character sanitization, prompt-injection detection, and PII redaction.
- `app/ai_service.py` — `google-genai` wrapper with deterministic fallback.
- `app/data/schemes.json` — 15 structured Indian public welfare, student, farmer, women, MSME, and senior citizen schemes.
- `static/` — Semantic, WCAG 2.1 AA-compliant single-page UI (`index.html`, `styles.css`, `app.js`).

### API Endpoints
- `GET /health` — Service health check and loaded scheme count.
- `GET /api/schemes` — Returns the full structured scheme catalog.
- `POST /api/evaluate` — Evaluates `UserContext`, returns ranked `eligible_schemes`, `near_match_schemes`, `not_eligible_schemes`, and `ai_guide`.

### Local Setup
```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# Linux/macOS:
# source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env  # Add GEMINI_API_KEY (optional; fallback works without it)
uvicorn app.main:app --reload --port 8080
```
Open `http://localhost:8080` in your browser.

### Testing
```bash
pytest -v
```
All tests run offline and fast by mocking `google-genai` calls.

### Google Cloud Run Deployment
```bash
gcloud run deploy civicbridge \
  --source . \
  --region asia-south1 \
  --allow-unauthenticated \
  --set-env-vars GEMINI_MODEL=gemini-3.5-flash-lite \
  --set-secrets GEMINI_API_KEY=GEMINI_API_KEY:latest
```

---

## 4. Security, Efficiency & Accessibility Highlights
- **PII Redaction Before LLM Calls:** Aadhaar numbers, PAN cards, Indian phone numbers, and email addresses are masked (`[REDACTED_AADHAAR]`, `[REDACTED_PAN]`, `[REDACTED_PHONE]`, `[REDACTED_EMAIL]`) before any text reaches the AI layer.
- **Prompt-Injection Defense:** Suspect instruction-override, system-prompt probing, role-hijack, and script-injection patterns are blocked with HTTP `400`.
- **HTTP Security Headers:** Enforces `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, and a strict `Content-Security-Policy` (`script-src 'self'`).
- **Lightweight & Cloud Run Ready:** Minimal dependencies (`fastapi`, `uvicorn`, `pydantic`, `google-genai`), non-root container user in `Dockerfile`, and `${PORT:-8080}` binding.
- **Accessibility (WCAG 2.1 AA):** Semantic HTML5 landmarks, skip-to-content link, high-contrast color palette, keyboard-navigable controls with `:focus-visible` rings, ARIA live regions (`aria-live="polite"`, `role="alert"`), interactive document checklist, and print/copy support.

---

## 5. Assumptions Made
- Eligibility rules are modeled on public central and state scheme thresholds (age, state, annual household income in INR, and occupation) for demonstration and rapid triage; citizens should confirm final deadlines and micro-criteria on the linked official portals.
- State-specific schemes (e.g., *Mukhyamantri Majhi Ladki Bahin Yojana* for Maharashtra) are evaluated against the selected State/UT, while national schemes use `["ALL"]`.
- `GEMINI_API_KEY` is optional in local development and CI because `ai_service.py` provides a deterministic fallback when the key is absent or unreachable.
