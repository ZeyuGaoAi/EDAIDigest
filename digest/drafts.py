from __future__ import annotations

from datetime import UTC, datetime, timedelta
from html import escape, unescape
from html.parser import HTMLParser
from pathlib import Path
import re

from digest.db import connect


VALID_STATUSES = ("new", "reviewed", "drafted", "approved", "sent", "rejected")
DEFAULT_LOOKBACK_DAYS = {"paper": 7, "funding": 30, "job": 30}
DEFAULT_MIN_SCORES = {"paper": 3.5, "funding": 3.5, "job": 2.0}
DEFAULT_MAX_ITEMS = {"paper": 5, "funding": 5, "job": 5}
DEFAULT_EMAIL_TEMPLATE = {
    "subject_prefix": "AI for Early Cancer Digest",
    "preheader": "Selected updates on AI for early cancer detection, screening, funding, and jobs.",
    "editor_note": "Draft for review. This issue covers papers from the past {paper_days} days, plus funding and jobs from the past {funding_days} days.",
    "body_template": '<p style="color: #5b6470;">{preheader}</p>\n<h1>AI for Early Cancer Digest - {date}</h1>\n<p><strong>Subject:</strong> {subject}</p>\n<p><strong>Editor note:</strong> {editor_note}</p>\n\n<h2>Papers</h2>\n{papers}\n\n<h2>Funding</h2>\n{funding}\n\n<h2>Jobs</h2>\n{jobs}\n\n<p style="color: #a33d2f;"><strong>Reply this email for any feedback!</strong></p>',
    "empty_text": "<p><em>No shortlisted items yet.</em></p>",
    "item_templates": {
        "paper": '<article>\n<h3>{title}</h3>\n<p><strong>Published in:</strong> {venue}</p>\n<p><strong>DOI / ID:</strong> {doi_or_id}</p>\n<p><strong>HTML:</strong> <a href="{html}">{html}</a></p>\n</article>',
        "funding": '<article>\n<h3>{title}</h3>\n<p><strong>Source:</strong> {source}</p>\n<p><strong>Link:</strong> <a href="{link}">{link}</a></p>\n</article>',
        "job": '<article>\n<h3>{title}</h3>\n<p><strong>Source:</strong> {source}</p>\n<p><strong>Link:</strong> <a href="{link}">{link}</a></p>\n</article>',
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
        match = re.search(r"/content/([^/]+?)(?:v\d+)?$", url)
        if match:
            return match.group(1)
    if "pubmed.ncbi.nlm.nih.gov/" in url:
        match = re.search(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)/", url)
        if match:
            return f"PMID:{match.group(1)}"
    return source


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
            WHERE status != 'rejected'
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

    grouped = {"paper": [], "funding": [], "job": []}
    for row in rows:
        if not _passes_score(row["category"], row["score"], min_scores):
            continue
        bucket = grouped.setdefault(row["category"], [])
        if len(bucket) < max_items.get(row["category"], DEFAULT_MAX_ITEMS[row["category"]]):
            bucket.append(row)
            selected_ids.append(row["id"])

    subject = f"{email_template['subject_prefix']} | {date_slug}"
    preheader = str(email_template["preheader"])
    editor_note = _format_template(
        email_template["editor_note"],
        {
            "date": date_slug,
            "paper_days": lookback_days["paper"],
            "funding_days": lookback_days["funding"],
            "job_days": lookback_days["job"],
        },
    )

    rendered_sections: dict[str, str] = {}
    for category in ("paper", "funding", "job"):
        if not grouped.get(category):
            rendered_sections[category] = email_template["empty_text"]
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
                "subject_prefix": escape(str(email_template["subject_prefix"])),
                "preheader": escape(preheader),
                "editor_note": escape(editor_note),
                "paper_days": lookback_days["paper"],
                "funding_days": lookback_days["funding"],
                "job_days": lookback_days["job"],
                "papers": rendered_sections["paper"],
                "funding": rendered_sections["funding"],
                "jobs": rendered_sections["job"],
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
