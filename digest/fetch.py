from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urljoin
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
    include_regex: str | None = None
    exclude_regex: str | None = None
    term: str | None = None
    retmax: int = 20
    sort: str = "pub date"
    max_items: int = 20
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


def _request_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


class AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.anchors: list[tuple[str, str]] = []
        self._current_href: str | None = None
        self._current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attr_map = dict(attrs)
        self._current_href = attr_map.get("href")
        self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._current_href is not None:
            self._current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._current_href is None:
            return
        text = " ".join(" ".join(self._current_text).split())
        if self._current_href and text:
            self.anchors.append((self._current_href, text))
        self._current_href = None
        self._current_text = []


def _child_text(element: ET.Element, path: str) -> str | None:
    child = element.find(path)
    if child is None:
        return None
    value = "".join(child.itertext()).strip()
    return value or None


def _date_node_to_string(date_node: ET.Element) -> str | None:
    medline = _child_text(date_node, "MedlineDate")
    if medline:
        return medline
    year = _child_text(date_node, "Year")
    month = _child_text(date_node, "Month") or "01"
    day = _child_text(date_node, "Day") or "01"
    if not year:
        return None
    month_map = {
        "Jan": "01",
        "Feb": "02",
        "Mar": "03",
        "Apr": "04",
        "May": "05",
        "Jun": "06",
        "Jul": "07",
        "Aug": "08",
        "Sep": "09",
        "Oct": "10",
        "Nov": "11",
        "Dec": "12",
    }
    month = month_map.get(month, month.zfill(2))
    day = day.zfill(2)
    return f"{year}-{month}-{day}"


def _pubmed_date(article: ET.Element) -> str | None:
    # Prefer electronic / indexing dates over future journal issue dates.
    article_date = article.find(".//ArticleDate")
    if article_date is not None:
        value = _date_node_to_string(article_date)
        if value:
            return value

    for status in ("pubmed", "entrez", "medline", "pmc-release"):
        date_node = article.find(f".//PubMedPubDate[@PubStatus='{status}']")
        if date_node is not None:
            value = _date_node_to_string(date_node)
            if value:
                return value

    pub_date = article.find(".//PubDate")
    if pub_date is not None:
        value = _date_node_to_string(pub_date)
        if value:
            return value
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


def fetch_pubmed(source: Source) -> list[dict[str, Any]]:
    if not source.term:
        raise ValueError(f"Source {source.name} does not define a PubMed search term")

    search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?" + urlencode(
        {
            "db": "pubmed",
            "term": source.term,
            "retmax": source.retmax,
            "sort": source.sort,
            "retmode": "xml",
        }
    )
    search_root = ET.fromstring(_request_text(search_url))
    pmids = [node.text.strip() for node in search_root.findall("./IdList/Id") if node.text]
    if not pmids:
        return []

    fetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?" + urlencode(
        {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml",
        }
    )
    fetch_root = ET.fromstring(_request_text(fetch_url))
    items: list[dict[str, Any]] = []
    for article in fetch_root.findall("./PubmedArticle"):
        pmid = _child_text(article, ".//PMID")
        title = _child_text(article, ".//ArticleTitle")
        abstract_parts = [
            "".join(node.itertext()).strip()
            for node in article.findall(".//Abstract/AbstractText")
            if "".join(node.itertext()).strip()
        ]
        summary = " ".join(abstract_parts) or None
        if not pmid or not title:
            continue
        items.append(
            {
                "title": title,
                "summary": summary,
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                "published_at": _pubmed_date(article),
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


def fetch_html_links(source: Source) -> list[dict[str, Any]]:
    if not source.url:
        raise ValueError(f"Source {source.name} does not define a URL")

    parser = AnchorParser()
    parser.feed(_request_text(source.url))

    include = re.compile(source.include_regex) if source.include_regex else None
    exclude = re.compile(source.exclude_regex) if source.exclude_regex else None

    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for href, text in parser.anchors:
        absolute_url = urljoin(source.url, href)
        haystack = f"{href} {absolute_url} {text}"
        if include and not include.search(haystack):
            continue
        if exclude and exclude.search(haystack):
            continue
        if absolute_url in seen:
            continue
        seen.add(absolute_url)
        items.append(
            {
                "title": text,
                "summary": None,
                "url": absolute_url,
                "published_at": None,
            }
        )
        if len(items) >= source.max_items:
            break
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
            elif source.kind == "html_links":
                items = fetch_html_links(source)
            elif source.kind == "pubmed":
                items = fetch_pubmed(source)
            elif source.kind == "manual":
                items = fetch_manual_file(source, config_path)
            else:
                raise ValueError(f"Unsupported source kind: {source.kind}")
            stats[source.name] = upsert_items(db_path, source, items)
        except Exception as exc:
            errors[source.name] = str(exc)
    return stats, errors
