from __future__ import annotations

from collections.abc import Iterable


EARLY_TERMS = (
    "early detection",
    "early diagnosis",
    "screening",
    "risk stratification",
    "precancer",
    "pre-cancer",
    "liquid biopsy",
    "surveillance",
)

CANCER_TERMS = (
    "cancer",
    "oncology",
    "tumor",
    "tumour",
    "neoplasm",
    "carcinoma",
)

AI_TERMS = (
    "artificial intelligence",
    "machine learning",
    "deep learning",
    "foundation model",
    "llm",
    "ai ",
    "computer vision",
)

NEGATIVE_TERMS = (
    "metastatic",
    "stage iv",
    "therapy",
    "treatment",
    "drug discovery",
    "anastomotic leak",
    "postoperative",
    "post-operative",
)


def _hits(text: str, keywords: Iterable[str]) -> int:
    normalized = f" {text.lower()} "
    return sum(1 for keyword in keywords if keyword in normalized)


def score_relevance(category: str, title: str, summary: str | None) -> float:
    haystack = f"{title}\n{summary or ''}"
    early_hits = _hits(haystack, EARLY_TERMS)
    cancer_hits = _hits(haystack, CANCER_TERMS)
    ai_hits = _hits(haystack, AI_TERMS)
    negative_hits = _hits(haystack, NEGATIVE_TERMS)
    score = (early_hits * 3.0) + (cancer_hits * 2.0) + (ai_hits * 2.0) - (negative_hits * 1.5)

    # Papers should strongly match all three axes: cancer, early detection, and AI.
    if category == "paper":
        if cancer_hits == 0:
            score -= 8.0
        if early_hits == 0:
            score -= 5.0
        if ai_hits == 0:
            score -= 4.0

    # Funding and jobs can be a bit broader, but still need a clear cancer signal.
    if category in {"funding", "job"} and cancer_hits == 0:
        score -= 5.0

    return round(max(score, 0.0), 2)


def why_relevant(title: str, summary: str | None) -> str:
    text = f"{title}\n{summary or ''}".lower()
    reasons: list[str] = []
    if any(term in text for term in EARLY_TERMS):
        reasons.append("mentions an early detection or screening context")
    if any(term in text for term in AI_TERMS):
        reasons.append("includes an AI or machine learning angle")
    if any(term in text for term in CANCER_TERMS):
        reasons.append("is clearly cancer-related")
    if not reasons:
        return "requires manual review for relevance"
    return "; ".join(reasons)
