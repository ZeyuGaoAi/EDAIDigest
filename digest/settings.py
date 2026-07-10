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
            "max_items": 5,
        },
        "funding": {
            "lookback_days": 30,
            "frequency": "monthly",
            "min_score": 3.5,
            "max_items": 5,
        },
        "job": {
            "lookback_days": 30,
            "frequency": "monthly",
            "min_score": 2.0,
            "max_items": 5,
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
    "distribution": {
        "sender_email": "zg323@cam.ac.uk",
        "recipient_emails": ["zg323@cam.ac.uk"],
        "email_subject": "AI for Early Cancer Digest | {date}",
    },
    "email_template": {
        "body_template": '<p style="color: #5b6470; margin: 0 0 8px;">Selected updates on AI for early cancer detection, screening, funding, and jobs.</p>\n<h1 style="margin: 0 0 8px;">AI for Early Cancer Digest - {date}</h1>\n<p style="color: #5b6470; margin: 0 0 24px;">Draft for review · Papers cover the past {paper_days} days · Funding and jobs cover the past {funding_days} days</p>\n\n<h2 style="margin: 24px 0 12px;">Papers</h2>\n{papers}\n\n<h2 style="margin: 24px 0 12px;">Funding</h2>\n{funding}\n\n<h2 style="margin: 24px 0 12px;">Jobs</h2>\n{jobs}\n\n<p style="color: #a33d2f; margin-top: 28px;">Reply this email for any feedback!</p>\n<p style="color: #5b6470; font-size: 12px; margin-top: 18px;"><em>Sources monitored: {sources}</em></p>',
        "item_templates": {
            "paper": '<div style="margin: 0 0 16px; padding-left: 18px; text-indent: -18px;">\n<span style="color: #a33d2f;">•</span> <a href="{html}" style="color: #16212b;">{title}</a><br>\n<span style="display: inline-block; margin-left: 18px; color: #5b6470; text-indent: 0;">Published in: {venue} · DOI / ID: {doi_or_id} · <a href="{html}">HTML</a></span>\n</div>',
            "funding": '<div style="margin: 0 0 16px; padding-left: 18px; text-indent: -18px;">\n<span style="color: #a33d2f;">•</span> <a href="{link}" style="color: #16212b;">{title}</a><br>\n<span style="display: inline-block; margin-left: 18px; color: #5b6470; text-indent: 0;">Source: {source} · <a href="{link}">View opportunity</a></span>\n</div>',
            "job": '<div style="margin: 0 0 16px; padding-left: 18px; text-indent: -18px;">\n<span style="color: #a33d2f;">•</span> <a href="{link}" style="color: #16212b;">{title}</a><br>\n<span style="display: inline-block; margin-left: 18px; color: #5b6470; text-indent: 0;">Source: {source} · <a href="{link}">View role</a></span>\n</div>',
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


def max_items_from_settings(settings: dict[str, Any]) -> dict[str, int]:
    cadence = settings.get("cadence", {})
    return {
        category: int(cadence.get(category, {}).get("max_items", DEFAULT_SETTINGS["cadence"][category]["max_items"]))
        for category in ("paper", "funding", "job")
    }
