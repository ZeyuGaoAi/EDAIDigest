from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from digest.db import connect


VALID_STATUSES = ("new", "reviewed", "drafted", "approved", "sent", "rejected")


def export_review_queue(db_path: Path, output_path: Path, lookback_days: int = 7, min_score: float = 3.5) -> Path:
    cutoff = (datetime.now(UTC) - timedelta(days=lookback_days)).isoformat()
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, title, source, category, published_at, score, summary, why_relevant, url, status
            FROM items
            WHERE status != 'rejected'
              AND COALESCE(published_at, fetched_at) >= ?
              AND score >= ?
            ORDER BY category, score DESC, COALESCE(published_at, fetched_at) DESC
            """,
            (cutoff, min_score),
        ).fetchall()

    lines = [
        "# Review Queue",
        "",
        "This file is intended for the Codex automation and the human reviewer.",
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
                    f"- Summary: {row['summary'] or 'No summary in source feed.'}",
                    f"- URL: {row['url']}",
                    "",
                ]
            )
    output_path.write_text("\n".join(lines))
    return output_path


def generate_template_draft(db_path: Path, drafts_dir: Path, lookback_days: int = 7, per_category: int = 3) -> Path:
    cutoff = (datetime.now(UTC) - timedelta(days=lookback_days)).isoformat()
    date_slug = datetime.now(UTC).date().isoformat()
    draft_path = drafts_dir / f"{date_slug}.md"
    drafts_dir.mkdir(parents=True, exist_ok=True)

    selected_ids: list[int] = []
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, title, source, category, summary, why_relevant, url
            FROM items
            WHERE status IN ('new', 'reviewed', 'drafted')
              AND COALESCE(published_at, fetched_at) >= ?
              AND score >= 3.5
            ORDER BY category, score DESC, COALESCE(published_at, fetched_at) DESC
            """,
            (cutoff,),
        ).fetchall()

    grouped = {"paper": [], "funding": [], "job": []}
    for row in rows:
        bucket = grouped.setdefault(row["category"], [])
        if len(bucket) < per_category:
            bucket.append(row)
            selected_ids.append(row["id"])

    lines = [
        f"# AI for Early Cancer Digest - {date_slug}",
        "",
        f"Subject: AI for Early Cancer Digest | {date_slug}",
        "",
        "Intro:",
        "A short editor note goes here.",
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
            lines.extend(
                [
                    f"### {row['title']}",
                    f"Source: {row['source']}",
                    f"Summary: {row['summary'] or 'Add one-line summary.'}",
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
