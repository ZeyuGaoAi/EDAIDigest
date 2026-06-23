from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_SETTINGS: dict[str, Any] = {
    "cadence": {
        "paper": {
            "lookback_days": 7,
            "frequency": "weekly",
            "min_score": 3.5,
        },
        "funding": {
            "lookback_days": 30,
            "frequency": "monthly",
            "min_score": 3.5,
        },
        "job": {
            "lookback_days": 30,
            "frequency": "monthly",
            "min_score": 2.0,
        },
    },
    "scope": {
        "paper": "AI for early cancer detection, screening, risk prediction, surveillance, liquid biopsy, and adjacent early-diagnosis methods.",
        "funding": "Calls, programmes, and announcements relevant to researchers building AI for early cancer detection.",
        "job": "Academic or research roles spanning AI, data science, imaging, biomarkers, screening, and prevention in cancer.",
    },
    "workflow": {
        "trigger": "Manual trigger while the scope is still being refined.",
        "review": "AI drafts the digest; a human reviews before anything is sent.",
    },
    "email_template": {
        "subject_prefix": "AI for Early Cancer Digest",
        "preheader": "Selected updates on AI for early cancer detection, screening, funding, and jobs.",
        "editor_note": "Draft for review. This issue covers papers from the past {paper_days} days, plus funding and jobs from the past {funding_days} days.",
        "body_template": "## Papers\n\n{papers}\n\n## Funding\n\n{funding}\n\n## Jobs\n\n{jobs}",
        "empty_text": "_No shortlisted items yet._",
        "item_templates": {
            "paper": "### {title}\nPublished in: {venue}\nDOI / ID: {doi_or_id}\nHTML: {html}",
            "funding": "### {title}\nSource: {source}\nSummary: {summary}\nWhy it matters: {why_relevant}\nLink: {link}",
            "job": "### {title}\nSource: {source}\nSummary: {summary}\nWhy it matters: {why_relevant}\nLink: {link}",
        },
    },
}


def _merge_defaults(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_defaults(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_settings(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return deepcopy(DEFAULT_SETTINGS)
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"Settings file must contain a JSON object: {path}")
    return _merge_defaults(DEFAULT_SETTINGS, payload)


def lookback_days_from_settings(settings: dict[str, Any]) -> dict[str, int]:
    cadence = settings.get("cadence", {})
    return {
        category: int(cadence.get(category, {}).get("lookback_days", DEFAULT_SETTINGS["cadence"][category]["lookback_days"]))
        for category in ("paper", "funding", "job")
    }


def min_scores_from_settings(settings: dict[str, Any]) -> dict[str, float]:
    cadence = settings.get("cadence", {})
    return {
        category: float(cadence.get(category, {}).get("min_score", DEFAULT_SETTINGS["cadence"][category]["min_score"]))
        for category in ("paper", "funding", "job")
    }
