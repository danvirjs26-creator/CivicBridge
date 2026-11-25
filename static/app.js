(() => {
  const form = document.getElementById("eligibility-form");
  const submitBtn = document.getElementById("submit-btn");
  const statusLive = document.getElementById("status-live");
  const errorBanner = document.getElementById("error-banner");
  const warningBanner = document.getElementById("warning-banner");
  const resultsSummary = document.getElementById("results-summary");
  const eligibleContainer = document.getElementById("eligible-container");
  const nearMatchContainer = document.getElementById("near-match-container");
  const notEligibleDetails = document.getElementById("not-eligible-details");
  const notEligibleSummary = document.getElementById("not-eligible-summary");
  const notEligibleContainer = document.getElementById("not-eligible-container");
  const guideMeta = document.getElementById("guide-meta");
  const guideContent = document.getElementById("guide-content");
  const copyGuideBtn = document.getElementById("copy-guide-btn");
  const printGuideBtn = document.getElementById("print-guide-btn");

  let lastGuideText = "";

  const PRESETS = {
    student: {
      age: 20,
      state: "Karnataka",
      occupation: "student",
      annual_income_inr: 180000,
      category_goal: "student",
      question: "Which scholarships can I apply for first?"
    },
    farmer: {
      age: 42,
      state: "Uttar Pradesh",
      occupation: "farmer",
      annual_income_inr: 160000,
      category_goal: "farmer",
      question: "How do I prioritize crop insurance and income support?"
    },
    women: {
      age: 30,
      state: "Maharashtra",
      occupation: "homemaker",
      annual_income_inr: 200000,
      category_goal: "women",
      question: "What Maharashtra women welfare schemes am I eligible for?"
    },
    msme: {
      age: 35,
      state: "Gujarat",
      occupation: "msme_owner",
      annual_income_inr: 350000,
      category_goal: "msme",
      question: "Which collateral-free business credit scheme fits best?"
    },
    senior: {
      age: 66,
      state: "Tamil Nadu",
      occupation: "retired",
      annual_income_inr: 120000,
      category_goal: "senior_citizen",
      question: "What pension and healthcare benefits can I claim?"
    }
  };

  document.querySelectorAll("[data-preset]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const preset = PRESETS[btn.dataset.preset];
      if (!preset) return;
      document.getElementById("age").value = preset.age;
      document.getElementById("state").value = preset.state;
      document.getElementById("occupation").value = preset.occupation;
      document.getElementById("annual_income_inr").value = preset.annual_income_inr;
      document.getElementById("category_goal").value = preset.category_goal;
      document.getElementById("question").value = preset.question;
      statusLive.textContent = `Loaded ${btn.textContent} sample profile.`;
    });
  });

  function clearBanners() {
    errorBanner.hidden = true;
    errorBanner.textContent = "";
    warningBanner.hidden = true;
    warningBanner.textContent = "";
  }

  function createSchemeCard(match) {
    const article = document.createElement("article");
    article.className = "scheme-card";

    const top = document.createElement("div");
    top.className = "scheme-top";

    const title = document.createElement("h3");
    title.className = "scheme-name";
    title.textContent = match.scheme.name;

    const badge = document.createElement("span");
    badge.className = "badge";
    if (match.status === "eligible") {
      badge.classList.add("badge-eligible");
      badge.textContent = "Eligible";
    } else if (match.status === "near_match") {
      badge.classList.add("badge-near");
      badge.textContent = "Near Match";
    } else {
      badge.classList.add("badge-ineligible");
      badge.textContent = "Not Eligible";
    }

    top.append(title, badge);
    article.appendChild(top);

    const scores = document.createElement("div");
    scores.className = "score-row";
    scores.textContent = `Match: ${match.match_score}%  •  Priority Score: ${match.priority_score}/100  •  Category: ${match.scheme.category.replace("_", " ")}`;
    article.appendChild(scores);

    const summary = document.createElement("p");
    summary.textContent = match.scheme.benefit_summary;
    article.appendChild(summary);

    if (match.matched_criteria.length > 0 || match.unmet_criteria.length > 0) {
      const ul = document.createElement("ul");
      ul.className = "criteria-list";
      match.matched_criteria.forEach((item) => {
        const li = document.createElement("li");
        li.className = "criteria-matched";
        li.textContent = `✓ ${item}`;
        ul.appendChild(li);
      });
      match.unmet_criteria.forEach((item) => {
        const li = document.createElement("li");
        li.className = "criteria-unmet";
        li.textContent = `✕ ${item}`;
        ul.appendChild(li);
      });
      article.appendChild(ul);
    }

    const docsWrap = document.createElement("div");
    docsWrap.className = "doc-tags";
    match.scheme.documents_required.forEach((doc) => {
      const span = document.createElement("span");
      span.className = "doc-tag";
      span.textContent = doc;
      docsWrap.appendChild(span);
    });
    article.appendChild(docsWrap);

    const link = document.createElement("a");
    link.className = "portal-link";
    link.href = match.scheme.official_portal;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = `Official Portal (${match.scheme.official_portal})`;
    article.appendChild(link);

    return article;
  }

  function renderSchemeGroup(container, headingText, matches) {
    container.replaceChildren();
    if (!matches.length) return;
    const h = document.createElement("h3");
    h.className = "group-title";
    h.textContent = `${headingText} (${matches.length})`;
    container.appendChild(h);
    matches.forEach((m) => container.appendChild(createSchemeCard(m)));
  }

  function renderAIGuide(guide) {
    guideContent.replaceChildren();
    if (!guide) {
      guideMeta.textContent = "";
      copyGuideBtn.disabled = true;
      printGuideBtn.disabled = true;
      return;
    }

    const sourceLabel = guide.source === "gemini" ? `Gemini (${guide.model_used})` : "Deterministic Verified Guide";
    guideMeta.textContent = `Source: ${sourceLabel}${guide.pii_redacted ? " • PII Redacted" : ""}`;

    const summaryP = document.createElement("p");
    summaryP.textContent = guide.summary;
    guideContent.appendChild(summaryP);

    if (guide.steps.length > 0) {
      const stepsHeading = document.createElement("h3");
      stepsHeading.textContent = "Recommended Next Steps";
      guideContent.appendChild(stepsHeading);

      const ol = document.createElement("ol");
      ol.className = "guide-steps";
      guide.steps.forEach((step) => {
        const li = document.createElement("li");
        const strong = document.createElement("strong");
        strong.textContent = `${step.title}: `;
        li.appendChild(strong);
        li.appendChild(document.createTextNode(step.description));
        ol.appendChild(li);
      });
      guideContent.appendChild(ol);
    }

    if (guide.document_checklist.length > 0) {
      const docHeading = document.createElement("h3");
      docHeading.textContent = "Interactive Document Checklist";
      guideContent.appendChild(docHeading);

      const ul = document.createElement("ul");
      ul.className = "checklist";
      guide.document_checklist.forEach((doc, idx) => {
        const li = document.createElement("li");
        const lbl = document.createElement("label");
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.id = `doc-check-${idx}`;
        lbl.appendChild(cb);
        lbl.appendChild(document.createTextNode(doc));
        li.appendChild(lbl);
        ul.appendChild(li);
      });
      guideContent.appendChild(ul);
    }

    lastGuideText = [
      "CivicBridge Action Guide",
      guide.summary,
      "",
      "Steps:",
      ...guide.steps.map((s) => `${s.step_number}. ${s.title}: ${s.description}`),
      "",
      "Document Checklist:",
      ...guide.document_checklist.map((d) => `- [ ] ${d}`)
    ].join("\n");

    copyGuideBtn.disabled = false;
    printGuideBtn.disabled = false;
  }

  copyGuideBtn.addEventListener("click", async () => {
    if (!lastGuideText) return;
    try {
      await navigator.clipboard.writeText(lastGuideText);
      statusLive.textContent = "Action guide copied to clipboard.";
    } catch {
      statusLive.textContent = "Copy unavailable in this browser context.";
    }
  });

  printGuideBtn.addEventListener("click", () => {
    window.print();
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    clearBanners();

    const payload = {
      age: Number(document.getElementById("age").value),
      state: document.getElementById("state").value,
      occupation: document.getElementById("occupation").value,
      annual_income_inr: Number(document.getElementById("annual_income_inr").value),
      category_goal: document.getElementById("category_goal").value,
      question: document.getElementById("question").value.trim() || null
    };

    submitBtn.disabled = true;
    statusLive.textContent = "Evaluating eligibility and generating guide...";

    try {
      const response = await fetch("/api/evaluate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "Unable to evaluate profile.");
      }

      if (data.warnings && data.warnings.length > 0) {
        warningBanner.textContent = data.warnings.join(" ");
        warningBanner.hidden = false;
      }

      resultsSummary.textContent =
        `Evaluated ${data.total_evaluated} schemes: ` +
        `${data.eligible_schemes.length} eligible, ` +
        `${data.near_match_schemes.length} near-match, ` +
        `${data.not_eligible_schemes.length} not eligible.`;

      renderSchemeGroup(eligibleContainer, "Eligible Schemes", data.eligible_schemes);
      renderSchemeGroup(nearMatchContainer, "Near-Match Schemes (1 Criterion Away)", data.near_match_schemes);

      notEligibleSummary.textContent = `Not Eligible Schemes (${data.not_eligible_schemes.length})`;
      renderSchemeGroup(notEligibleContainer, "Not Eligible", data.not_eligible_schemes);
      notEligibleDetails.hidden = data.not_eligible_schemes.length === 0;

      renderAIGuide(data.ai_guide);
      statusLive.textContent = "Evaluation complete.";
    } catch (err) {
      errorBanner.textContent = err.message || "An unexpected error occurred.";
      errorBanner.hidden = false;
      statusLive.textContent = "Evaluation failed.";
    } finally {
      submitBtn.disabled = false;
    }
  });
})();
