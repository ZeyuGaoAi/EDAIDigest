from __future__ import annotations

from datetime import UTC, datetime, timedelta
from html import escape, unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import re

from digest.db import connect


VALID_STATUSES = ("new", "reviewed", "drafted", "approved", "sent", "rejected", "expired")
DEFAULT_LOOKBACK_DAYS = {"paper": 7, "funding": 30, "job": 30}
DEFAULT_MIN_SCORES = {"paper": 3.5, "funding": 3.5, "job": 2.0}
DEFAULT_MAX_ITEMS = {"paper": 5, "funding": 5, "job": 5}
DEFAULT_EMAIL_SUBJECT = "AI for Early Cancer Digest | {date}"
DEFAULT_EMPTY_TEXT = "<p><em>No shortlisted items yet.</em></p>"
DEFAULT_SUBJECT_PREFIX = "AI for Early Cancer Digest"
DEFAULT_PREHEADER = "Selected updates on AI for early cancer detection, screening, funding, and jobs."
DEFAULT_EDITOR_NOTE = "Draft for review. This issue covers papers from the past {paper_days} days, plus funding and jobs from the past {funding_days} days."
DEFAULT_EMAIL_TEMPLATE = {
    "body_template": '<p style="color: #5b6470; margin: 0 0 8px;">Selected updates on AI for early cancer detection, screening, funding, and jobs.</p>\n<h1 style="margin: 0 0 8px;">AI for Early Cancer Digest - {date}</h1>\n<p style="color: #5b6470; margin: 0 0 24px;">Draft for review · Papers cover the past {paper_days} days · Funding and jobs cover the past {funding_days} days</p>\n\n<h2 style="margin: 24px 0 12px;">Papers</h2>\n{papers}\n\n<h2 style="margin: 24px 0 12px;">Funding</h2>\n{funding}\n\n<h2 style="margin: 24px 0 12px;">Jobs</h2>\n{jobs}\n\n<p style="color: #a33d2f; margin-top: 28px;">Reply this email for any feedback!</p>\n<p style="color: #5b6470; font-size: 12px; margin-top: 18px;"><em>Sources monitored: {sources}</em></p>',
    "item_templates": {
        "paper": '<div style="margin: 0 0 16px; padding-left: 18px; text-indent: -18px;">\n<span style="color: #a33d2f;">•</span> <a href="{html}" style="color: #16212b;">{title}</a><br>\n<span style="display: inline-block; margin-left: 18px; color: #5b6470; text-indent: 0;">Published in: {venue} · DOI / ID: {doi_or_id} · <a href="{html}">HTML</a></span>\n</div>',
        "funding": '<div style="margin: 0 0 16px; padding-left: 18px; text-indent: -18px;">\n<span style="color: #a33d2f;">•</span> <a href="{link}" style="color: #16212b;">{title}</a><br>\n<span style="display: inline-block; margin-left: 18px; color: #5b6470; text-indent: 0;">Source: {source} · <a href="{link}">View opportunity</a></span>\n</div>',
        "job": '<div style="margin: 0 0 16px; padding-left: 18px; text-indent: -18px;">\n<span style="color: #a33d2f;">•</span> <a href="{link}" style="color: #16212b;">{title}</a><br>\n<span style="display: inline-block; margin-left: 18px; color: #5b6470; text-indent: 0;">Source: {source} · <a href="{link}">View role</a></span>\n</div>',
    },
}


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _format_template(template: str, values: dict[str, object]) -> str:
    return template.format_map(_SafeDict({key: "" if value is None else value for key, value in values.items()}))


def _category_cutoff(category: str, lookback_days: dict[str, int]) -> str:
    days = lookback_days.get(category, DEFAULT_LOOKBACK_DAYS[category])
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def _category_filter_sql(lookback_days: dict[str, int]) -> tuple[str, list[str]]:
    clauses: list[str] = []
    params: list[str] = []
    for category in ("paper", "funding", "job"):
        clauses.append("(category = ? AND COALESCE(published_at, fetched_at) >= ?)")
        params.extend([category, _category_cutoff(category, lookback_days)])
    return " OR ".join(clauses), params


def _clean_summary(summary: str | None, limit: int = 420) -> str:
    if not summary:
        return "Add one-line summary."
    text = re.sub(r"<[^>]+>", " ", unescape(summary))
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    trimmed = text[: limit - 1].rsplit(" ", 1)[0].strip()
    return f"{trimmed}..."


class _HTMLToTextParser(HTMLParser):
    block_tags = {"article", "br", "div", "h1", "h2", "h3", "h4", "li", "p", "section"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self.block_tags:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.block_tags:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        text = unescape("".join(self.parts))
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return "\n".join(line.strip() for line in text.strip().splitlines())


def _html_to_text(html: str) -> str:
    parser = _HTMLToTextParser()
    parser.feed(html)
    return parser.text()


def _markdownish_to_html(text: str) -> str:
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            lines.append("")
        elif re.search(r"</?(h[1-6]|p|article|div|section|ul|ol|li|a|strong|em)\b", line, re.IGNORECASE):
            lines.append(line)
        elif line.startswith("### "):
            lines.append(f"<h3>{escape(line[4:])}</h3>")
        elif line.startswith("## "):
            lines.append(f"<h2>{escape(line[3:])}</h2>")
        elif line.startswith("# "):
            lines.append(f"<h1>{escape(line[2:])}</h1>")
        elif line.startswith("- "):
            lines.append(f"<p>{escape(line[2:])}</p>")
        elif ": " in line and not line.startswith(("http://", "https://")):
            key, value = line.split(": ", 1)
            value_html = escape(value)
            if value.startswith(("http://", "https://")):
                href = escape(value, quote=True)
                value_html = f'<a href="{href}">{escape(value)}</a>'
            lines.append(f"<p><strong>{escape(key)}:</strong> {value_html}</p>")
        else:
            lines.append(f"<p>{escape(line)}</p>")
    return "\n".join(lines)


def _ensure_html_fragment(text: str) -> str:
    return _markdownish_to_html(text)


def _email_html_document(subject: str, body: str) -> str:
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{escape(subject)}</title>
</head>
<body style="font-family: Georgia, 'Times New Roman', serif; color: #16212b; line-height: 1.5;">
  {body}
</body>
</html>
"""


def _email_text_document(body_html: str) -> str:
    return _html_to_text(body_html)


def _passes_score(category: str, score: float | None, min_scores: dict[str, float]) -> bool:
    threshold = min_scores.get(category, DEFAULT_MIN_SCORES[category])
    return (score or 0.0) >= threshold


def _paper_identifier(source: str, url: str) -> str:
    if "arxiv.org/abs/" in url:
        return f"arXiv:{url.rsplit('/', 1)[-1]}"
    if "medrxiv.org/content/" in url:
        match = re.search(r"/content/(.+?)(?:v\d+)?/?$", url)
        if match:
            return match.group(1)
    if "pubmed.ncbi.nlm.nih.gov/" in url:
        match = re.search(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)/", url)
        if match:
            return f"PMID:{match.group(1)}"
    return source


def _source_attribution(source_config_path: Path | None) -> str:
    if source_config_path is None or not source_config_path.exists():
        return "Source configuration unavailable"
    payload = json.loads(source_config_path.read_text())
    grouped = {"paper": [], "funding": [], "job": []}
    for source in payload:
        if not isinstance(source, dict):
            continue
        category = source.get("category")
        name = source.get("name")
        if category in grouped and isinstance(name, str) and name:
            grouped[category].append(name)
    labels = {"paper": "Papers", "funding": "Funding", "job": "Jobs"}
    return " | ".join(
        f"{labels[category]}: {', '.join(names)}"
        for category, names in grouped.items()
        if names
    ) or "Source configuration unavailable"


def _source_selection_rules(source_config_path: Path | None) -> dict[str, dict[str, tuple[int, int | None]]]:
    """Return active source names plus optional priority and per-source digest caps."""
    if source_config_path is None or not source_config_path.exists():
        return {}
    try:
        payload = json.loads(source_config_path.read_text())
    except json.JSONDecodeError:
        return {}

    rules: dict[str, dict[str, tuple[int, int | None]]] = {}
    for source in payload:
        if not isinstance(source, dict):
            continue
        category = source.get("category")
        name = source.get("name")
        if not isinstance(category, str) or not isinstance(name, str) or not name:
            continue
        try:
            priority = int(source.get("priority", 100))
        except (TypeError, ValueError):
            priority = 100
        try:
            cap_value = source.get("max_digest_items")
            cap = int(cap_value) if cap_value is not None else None
        except (TypeError, ValueError):
            cap = None
        rules.setdefault(category, {})[name] = (priority, cap if cap and cap > 0 else None)
    return rules


def export_review_queue(
    db_path: Path,
    output_path: Path,
    lookback_days: dict[str, int] | None = None,
    min_scores: dict[str, float] | None = None,
) -> Path:
    lookback_days = lookback_days or DEFAULT_LOOKBACK_DAYS
    min_scores = min_scores or DEFAULT_MIN_SCORES
    category_filter_sql, category_params = _category_filter_sql(lookback_days)
    with connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT id, title, source, category, published_at, score, summary, why_relevant, url, status
            FROM items
            WHERE status NOT IN ('rejected', 'expired')
              AND ({category_filter_sql})
            ORDER BY category, score DESC, COALESCE(published_at, fetched_at) DESC
            """,
            category_params,
        ).fetchall()
    rows = [row for row in rows if _passes_score(row["category"], row["score"], min_scores)]

    lines = [
        "# Review Queue",
        "",
        "This file is intended for the Codex automation and the human reviewer.",
        f"Papers use a {lookback_days['paper']}-day window; funding and jobs use {lookback_days['funding']}- and {lookback_days['job']}-day windows respectively.",
        "",
    ]
    grouped = {"paper": [], "funding": [], "job": []}
    for row in rows:
        grouped.setdefault(row["category"], []).append(row)

    for category in ("paper", "funding", "job"):
        lines.append(f"## {category.title()}s")
        lines.append("")
        if not grouped.get(category):
            lines.append("_No candidates found._")
            lines.append("")
            continue
        for row in grouped[category]:
            published = row["published_at"] or "unknown date"
            lines.extend(
                [
                    f"### Item {row['id']}: {row['title']}",
                    f"- Source: {row['source']}",
                    f"- Published: {published}",
                    f"- Score: {row['score']}",
                    f"- Status: {row['status']}",
                    f"- Why relevant: {row['why_relevant']}",
                    f"- Summary: {_clean_summary(row['summary'], limit=600)}",
                    f"- URL: {row['url']}",
                    "",
                ]
            )
    output_path.write_text("\n".join(lines))
    return output_path


def generate_template_draft(
    db_path: Path,
    drafts_dir: Path,
    lookback_days: dict[str, int] | None = None,
    min_scores: dict[str, float] | None = None,
    email_template: dict[str, str] | None = None,
    max_items: dict[str, int] | None = None,
    email_subject_template: str | None = None,
    source_config_path: Path | None = None,
) -> Path:
    lookback_days = lookback_days or DEFAULT_LOOKBACK_DAYS
    min_scores = min_scores or DEFAULT_MIN_SCORES
    max_items = max_items or DEFAULT_MAX_ITEMS
    email_template = {**DEFAULT_EMAIL_TEMPLATE, **(email_template or {})}
    item_templates = {
        **DEFAULT_EMAIL_TEMPLATE["item_templates"],
        **email_template.get("item_templates", {}),
    }
    category_filter_sql, category_params = _category_filter_sql(lookback_days)
    date_slug = datetime.now(UTC).date().isoformat()
    draft_path = drafts_dir / f"{date_slug}.html"
    text_path = drafts_dir / f"{date_slug}.txt"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    source_rules = _source_selection_rules(source_config_path)

    selected_ids: list[int] = []
    with connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT id, title, source, venue, category, summary, why_relevant, url, score
            FROM items
            WHERE status IN ('new', 'reviewed', 'drafted')
              AND ({category_filter_sql})
            ORDER BY category, score DESC, COALESCE(published_at, fetched_at) DESC
            """,
            category_params,
        ).fetchall()

    candidates = {"paper": [], "funding": [], "job": []}
    for row in rows:
        if not _passes_score(row["category"], row["score"], min_scores):
            continue
        category_rules = source_rules.get(row["category"], {})
        # Configuration defines the active sources, so retired feeds cannot
        # resurface from historical rows in the database.
        if category_rules and row["source"] not in category_rules:
            continue
        candidates.setdefault(row["category"], []).append(row)

    grouped = {"paper": [], "funding": [], "job": []}
    for category, category_candidates in candidates.items():
        category_rules = source_rules.get(category, {})
        # The database query already orders equal-priority candidates by score
        # and recency. Stable sorting adds source precedence without losing it.
        category_candidates.sort(
            key=lambda row: category_rules.get(row["source"], (100, None))[0]
        )
        source_counts: dict[str, int] = {}
        for row in category_candidates:
            if len(grouped[category]) >= max_items.get(category, DEFAULT_MAX_ITEMS[category]):
                break
            _, source_cap = category_rules.get(row["source"], (100, None))
            if source_cap is not None and source_counts.get(row["source"], 0) >= source_cap:
                continue
            grouped[category].append(row)
            source_counts[row["source"]] = source_counts.get(row["source"], 0) + 1
            selected_ids.append(row["id"])

    legacy_values = {
        "date": date_slug,
        "paper_days": lookback_days["paper"],
        "funding_days": lookback_days["funding"],
        "job_days": lookback_days["job"],
    }
    subject = _format_template(email_subject_template or DEFAULT_EMAIL_SUBJECT, {"date": date_slug})

    rendered_sections: dict[str, str] = {}
    for category in ("paper", "funding", "job"):
        if not grouped.get(category):
            rendered_sections[category] = _ensure_html_fragment(str(email_template.get("empty_text", DEFAULT_EMPTY_TEXT)))
            continue
        rendered_items: list[str] = []
        for row in grouped[category]:
            rendered = _format_template(
                item_templates[category],
                {
                    "title": escape(row["title"] or ""),
                    "source": escape(row["source"] or ""),
                    "venue": escape(row["venue"] or row["source"] or ""),
                    "doi_or_id": escape(_paper_identifier(row["source"] or "", row["url"] or "")),
                    "html": escape(row["url"] or "", quote=True),
                    "link": escape(row["url"] or "", quote=True),
                    "summary": escape(_clean_summary(row["summary"])),
                    "why_relevant": escape(row["why_relevant"] or ""),
                },
            )
            rendered_items.append(_ensure_html_fragment(rendered))
        rendered_sections[category] = "\n\n".join(rendered_items)

    body_html = _ensure_html_fragment(
        _format_template(
            email_template["body_template"],
            {
                "date": date_slug,
                "subject": escape(subject),
                "subject_prefix": escape(str(email_template.get("subject_prefix", DEFAULT_SUBJECT_PREFIX))),
                "preheader": escape(str(email_template.get("preheader", DEFAULT_PREHEADER))),
                "editor_note": escape(_format_template(str(email_template.get("editor_note", DEFAULT_EDITOR_NOTE)), legacy_values)),
                "paper_days": lookback_days["paper"],
                "funding_days": lookback_days["funding"],
                "job_days": lookback_days["job"],
                "papers": rendered_sections["paper"],
                "funding": rendered_sections["funding"],
                "jobs": rendered_sections["job"],
                "sources": escape(_source_attribution(source_config_path)),
            },
        )
    )
    draft_path.write_text(_email_html_document(subject, body_html))
    text_path.write_text(_email_text_document(body_html))
    if selected_ids:
        with connect(db_path) as conn:
            conn.executemany(
                "UPDATE items SET status = 'drafted' WHERE id = ? AND status IN ('new', 'reviewed')",
                [(item_id,) for item_id in selected_ids],
            )
            conn.commit()
    return draft_path


def set_status(db_path: Path, item_id: int, status: str) -> None:
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status}")
    with connect(db_path) as conn:
        conn.execute("UPDATE items SET status = ? WHERE id = ?", (status, item_id))
        conn.commit()
