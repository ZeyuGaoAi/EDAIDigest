from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_EMAIL_TEMPLATE = {
    "body_template": '''<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background: #f5f1ec; font-family: Verdana, Geneva, sans-serif; color: #292537;">
<tr><td align="center" style="padding: 24px 12px;">
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="620" style="width: 100%; max-width: 620px; background: #ffffff; border-top: 6px solid #7b4d89;">
<tr><td style="padding: 28px 34px 14px;">
<a href="https://esac-network.eu/" style="text-decoration: none;"><img src="https://esac-network.eu/wp-content/uploads/2025/04/ESAC-LOGO-LARGE-300x169.png" width="132" height="74" alt="ESAC" style="display: block; width: 132px; height: 74px; border: 0;"></a>
<p style="margin: 22px 0 9px; color: #7b4d89; font-size: 11px; font-weight: 700; letter-spacing: 2px; text-transform: uppercase;">Early detection briefing &nbsp; / &nbsp; {date}</p>
<h1 style="margin: 0 0 16px; color: #292537; font-family: Georgia, 'Times New Roman', serif; font-size: 34px; line-height: 1.16; font-weight: 700;">AI for Early Cancer<br>Digest</h1>
<p style="margin: 0 0 12px; color: #4f4b58; font-size: 15px; line-height: 1.65;">Selected papers, funding calls and research roles for the early detection community.</p>
<p style="margin: 0; color: #696273; font-size: 12px; line-height: 1.6;">This digest is based on an automated search supported by the ESAC Early Detection Working Group.</p>
</td></tr>
<tr><td style="padding: 8px 34px 30px;">
<h2 style="margin: 22px 0 4px; padding: 0 0 10px; border-bottom: 2px solid #7b4d89; color: #292537; font-family: Georgia, 'Times New Roman', serif; font-size: 23px;">🔬 Papers</h2>
<p style="margin: 0 0 14px; color: #817987; font-size: 11px;">Published in the past {paper_days} days</p>
{papers}
<h2 style="margin: 34px 0 4px; padding: 0 0 10px; border-bottom: 2px solid #7b4d89; color: #292537; font-family: Georgia, 'Times New Roman', serif; font-size: 23px;">💡 Funding</h2>
<p style="margin: 0 0 14px; color: #817987; font-size: 11px;">Opportunities from the past {funding_days} days</p>
{funding}
<h2 style="margin: 34px 0 4px; padding: 0 0 10px; border-bottom: 2px solid #7b4d89; color: #292537; font-family: Georgia, 'Times New Roman', serif; font-size: 23px;">💼 Jobs</h2>
<p style="margin: 0 0 14px; color: #817987; font-size: 11px;">Roles from the past {job_days} days</p>
{jobs}
</td></tr>
<tr><td style="padding: 22px 34px 26px; background: #faf7f3; border-top: 1px solid #e8e2df;">
<p style="margin: 0 0 15px; color: #a33d2f; font-size: 13px; font-weight: 700;">Reply this email for any feedback!</p>
<p style="margin: 0; color: #817987; font-size: 11px; line-height: 1.6;"><em>Sources monitored: {sources}</em></p>
</td></tr>
</table>
</td></tr>
</table>''',
    "item_templates": {
        "paper": '<div style="padding: 12px 0 15px; border-bottom: 1px solid #ece7e3;">\n<a href="{html}" style="color: #292537; font-family: Georgia, \'Times New Roman\', serif; font-size: 17px; line-height: 1.4; text-decoration: none;">{title}</a><br>\n<span style="display: inline-block; padding: 7px 0 0 14px; color: #696273; font-size: 11px; line-height: 1.6;">↳ {venue} &nbsp;·&nbsp; {doi_or_id} &nbsp;·&nbsp; <a href="{html}" style="color: #7b4d89;">HTML</a></span>\n</div>',
        "funding": '<div style="padding: 12px 0 15px; border-bottom: 1px solid #ece7e3;">\n<a href="{link}" style="color: #292537; font-family: Georgia, \'Times New Roman\', serif; font-size: 17px; line-height: 1.4; text-decoration: none;">{title}</a><br>\n<span style="display: inline-block; padding: 7px 0 0 14px; color: #696273; font-size: 11px; line-height: 1.6;">↳ {source} &nbsp;·&nbsp; <a href="{link}" style="color: #7b4d89;">View opportunity</a></span>\n</div>',
        "job": '<div style="padding: 12px 0 15px; border-bottom: 1px solid #ece7e3;">\n<a href="{link}" style="color: #292537; font-family: Georgia, \'Times New Roman\', serif; font-size: 17px; line-height: 1.4; text-decoration: none;">{title}</a><br>\n<span style="display: inline-block; padding: 7px 0 0 14px; color: #696273; font-size: 11px; line-height: 1.6;">↳ {source} &nbsp;·&nbsp; <a href="{link}" style="color: #7b4d89;">View role</a></span>\n</div>',
    },
}


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
        "review": "Codex reads each candidate title and abstract, marks it reviewed or rejected, then generates the digest from reviewed items only.",
    },
    "distribution": {
        "sender_email": "zg323@cam.ac.uk",
        "recipient_emails": ["zg323@cam.ac.uk"],
        "email_subject": "AI for Early Cancer Digest | {date}",
    },
    "email_template": deepcopy(DEFAULT_EMAIL_TEMPLATE),
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
