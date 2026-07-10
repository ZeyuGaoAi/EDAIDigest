from __future__ import annotations

from collections.abc import Iterable
import re


EARLY_TERMS = (
    "early detection",
    "early diagnosis",
    "screening",
    "risk stratification",
    "cancer prevention",
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
    "ai",
    "computer vision",
)

TREATMENT_TERMS = (
    "metastatic",
    "stage iv",
    "therapy",
    "treatment",
    "drug discovery",
    "anastomotic leak",
    "postoperative",
    "post-operative",
)

FUNDING_TERMS = (
    "grant",
    "funding",
    "call for proposals",
    "funding opportunity",
    "award",
    "fellowship",
    "scheme",
    "programme",
    "program",
)

JOB_DOMAIN_TERMS = (
    "data science",
    "computational",
    "imaging",
    "biomarker",
    "bioinformatics",
    "health informatics",
)


def _hits(text: str, keywords: Iterable[str]) -> int:
    return sum(
        1
        for keyword in keywords
        if re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", text, re.IGNORECASE)
    )


def score_relevance(category: str, title: str, summary: str | None) -> float:
    haystack = f"{title}\n{summary or ''}"
    early_hits = _hits(haystack, EARLY_TERMS)
    cancer_hits = _hits(haystack, CANCER_TERMS)
    ai_hits = _hits(haystack, AI_TERMS)
    treatment_hits = _hits(haystack, TREATMENT_TERMS)
    funding_hits = _hits(haystack, FUNDING_TERMS)
    job_domain_hits = _hits(haystack, JOB_DOMAIN_TERMS)

    # The digest is intentionally narrow. Returning no item is better than
    # presenting generic cancer news, jobs, or treatment research as relevant.
    if category == "paper" and (not all((early_hits, cancer_hits, ai_hits)) or treatment_hits):
        return 0.0
    if category == "funding" and (cancer_hits == 0 or funding_hits == 0 or (early_hits == 0 and ai_hits == 0)):
        return 0.0
    if category == "job" and (cancer_hits == 0 or (early_hits == 0 and ai_hits == 0 and job_domain_hits == 0)):
        return 0.0

    score = (early_hits * 3.0) + (cancer_hits * 2.0) + (ai_hits * 2.0) + (funding_hits * 1.0) + (job_domain_hits * 1.0)
    return round(score, 2)


def why_relevant(title: str, summary: str | None) -> str:
    text = f"{title}\n{summary or ''}".lower()
    reasons: list[str] = []
    if _hits(text, EARLY_TERMS):
        reasons.append("mentions an early detection or screening context")
    if _hits(text, AI_TERMS):
        reasons.append("includes an AI or machine learning angle")
    if _hits(text, CANCER_TERMS):
        reasons.append("is clearly cancer-related")
    if not reasons:
        return "requires manual review for relevance"
    return "; ".join(reasons)
