from __future__ import annotations

from datetime import UTC, datetime, timedelta
from html import unescape
from pathlib import Path
import re

from digest.db import connect


VALID_STATUSES = ("new", "reviewed", "drafted", "approved", "sent", "rejected")
DEFAULT_LOOKBACK_DAYS = {"paper": 7, "funding": 30, "job": 30}
DEFAULT_MIN_SCORES = {"paper": 3.5, "funding": 3.5, "job": 2.0}
DEFAULT_EMAIL_TEMPLATE = {
    "subject_prefix": "AI for Early Cancer Digest",
    "preheader": "Selected updates on AI for early cancer detection, screening, funding, and jobs.",
    "editor_note": "Draft for review. This issue covers papers from the past {paper_days} days, plus funding and jobs from the past {funding_days} days.",
}


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
    per_category: int = 3,
) -> Path:
    lookback_days = lookback_days or DEFAULT_LOOKBACK_DAYS
    min_scores = min_scores or DEFAULT_MIN_SCORES
    email_template = {**DEFAULT_EMAIL_TEMPLATE, **(email_template or {})}
    category_filter_sql, category_params = _category_filter_sql(lookback_days)
    date_slug = datetime.now(UTC).date().isoformat()
    draft_path = drafts_dir / f"{date_slug}.md"
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
        if len(bucket) < per_category:
            bucket.append(row)
            selected_ids.append(row["id"])

    lines = [
        f"# AI for Early Cancer Digest - {date_slug}",
        "",
        f"Subject: {email_template['subject_prefix']} | {date_slug}",
        "",
        "Preheader:",
        email_template["preheader"],
        "",
        "Editor note:",
        email_template["editor_note"].format(
            date=date_slug,
            paper_days=lookback_days["paper"],
            funding_days=lookback_days["funding"],
            job_days=lookback_days["job"],
        ),
        "",
    ]
    for category in ("paper", "funding", "job"):
        label = category.title() + ("s" if category != "funding" else "")
        lines.append(f"## {label}")
        lines.append("")
        if not grouped.get(category):
            lines.append("_No shortlisted items yet._")
            lines.append("")
            continue
        for row in grouped[category]:
            if category == "paper":
                lines.extend(
                    [
                        f"### {row['title']}",
                        f"Published in: {row['venue'] or row['source']}",
                        f"DOI / ID: {_paper_identifier(row['source'], row['url'])}",
                        f"HTML: {row['url']}",
                        "",
                    ]
                )
                continue
            lines.extend(
                [
                    f"### {row['title']}",
                    f"Source: {row['source']}",
                    f"Summary: {_clean_summary(row['summary'])}",
                    f"Why it matters: {row['why_relevant']}",
                    f"Link: {row['url']}",
                    "",
                ]
            )
    draft_path.write_text("\n".join(lines))
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
