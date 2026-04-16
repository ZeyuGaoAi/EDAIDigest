from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from digest.db import connect
from digest.relevance import score_relevance, why_relevant


USER_AGENT = "ai-early-cancer-digest/0.1"


@dataclass
class Source:
    name: str
    category: str
    url: str | None = None
    path: str | None = None
    kind: str = "rss"


def load_sources(config_path: Path) -> list[Source]:
    payload = json.loads(config_path.read_text())
    return [Source(**item) for item in payload]


def _text_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _parse_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return _text_or_none(value)
    return parsed.astimezone(UTC).isoformat()


def _entry_text(entry: ET.Element, names: tuple[str, ...]) -> str | None:
    for name in names:
        child = entry.find(name)
        if child is not None and child.text:
            return child.text.strip()
    return None


def _entry_link(entry: ET.Element) -> str | None:
    for candidate in entry.findall("{http://www.w3.org/2005/Atom}link"):
        href = candidate.attrib.get("href")
        if href:
            return href.strip()
    link = entry.find("link")
    if link is not None:
        if link.text:
            return link.text.strip()
        href = link.attrib.get("href")
        if href:
            return href.strip()
    return None


def fetch_feed(source: Source) -> list[dict[str, Any]]:
    if not source.url:
        raise ValueError(f"Source {source.name} does not define a URL")
    request = Request(source.url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=30) as response:
        payload = response.read()
    root = ET.fromstring(payload)
    items: list[dict[str, Any]] = []

    atom_entries = root.findall("{http://www.w3.org/2005/Atom}entry")
    rss_entries = root.findall("./channel/item")
    entries = atom_entries or rss_entries

    for entry in entries:
        title = _entry_text(entry, ("title", "{http://www.w3.org/2005/Atom}title"))
        summary = _entry_text(
            entry,
            ("description", "summary", "{http://www.w3.org/2005/Atom}summary"),
        )
        link = _entry_link(entry)
        published_at = _parse_date(
            _entry_text(
                entry,
                ("pubDate", "published", "updated", "{http://www.w3.org/2005/Atom}published"),
            )
        )
        if not title or not link:
            continue
        items.append(
            {
                "title": title,
                "summary": summary,
                "url": link,
                "published_at": published_at,
            }
        )
    return items


def fetch_manual_file(source: Source, config_path: Path) -> list[dict[str, Any]]:
    if not source.path:
        raise ValueError(f"Source {source.name} does not define a path")
    manual_path = (config_path.parent / source.path).resolve()
    payload = json.loads(manual_path.read_text())
    items: list[dict[str, Any]] = []
    for entry in payload:
        title = entry.get("title")
        url = entry.get("url")
        if not title or not url:
            continue
        items.append(
            {
                "title": title,
                "summary": entry.get("summary"),
                "url": url,
                "published_at": entry.get("published_at"),
            }
        )
    return items


def upsert_items(db_path: Path, source: Source, items: list[dict[str, Any]]) -> int:
    inserted = 0
    fetched_at = datetime.now(UTC).isoformat()
    with connect(db_path) as conn:
        for item in items:
            summary = item.get("summary")
            score = score_relevance(source.category, item["title"], summary)
            content_hash = hashlib.sha256(
                f"{item['title']}|{item['url']}|{summary or ''}".encode("utf-8")
            ).hexdigest()
            cursor = conn.execute(
                """
                INSERT INTO items (
                    url, title, source, category, published_at, fetched_at,
                    score, summary, why_relevant, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    title=excluded.title,
                    source=excluded.source,
                    category=excluded.category,
                    published_at=COALESCE(excluded.published_at, items.published_at),
                    fetched_at=excluded.fetched_at,
                    score=excluded.score,
                    summary=COALESCE(excluded.summary, items.summary),
                    why_relevant=excluded.why_relevant,
                    content_hash=excluded.content_hash
                """,
                (
                    item["url"],
                    item["title"],
                    source.name,
                    source.category,
                    item.get("published_at"),
                    fetched_at,
                    score,
                    summary,
                    why_relevant(item["title"], summary),
                    content_hash,
                ),
            )
            inserted += 1 if cursor.rowcount == 1 else 0
        conn.commit()
    return inserted


def ingest(db_path: Path, config_path: Path) -> tuple[dict[str, int], dict[str, str]]:
    stats: dict[str, int] = {}
    errors: dict[str, str] = {}
    for source in load_sources(config_path):
        try:
            if source.kind == "rss":
                items = fetch_feed(source)
            elif source.kind == "manual":
                items = fetch_manual_file(source, config_path)
            else:
                raise ValueError(f"Unsupported source kind: {source.kind}")
            stats[source.name] = upsert_items(db_path, source, items)
        except Exception as exc:
            errors[source.name] = str(exc)
    return stats, errors
