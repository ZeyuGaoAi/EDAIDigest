from __future__ import annotations

from datetime import UTC, datetime
from html import escape
from pathlib import Path
import re

from digest.db import connect


def _format_timestamp(value: str | None) -> str:
    if not value:
        return "Unknown"
    try:
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return value
    return dt.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _linkify(text: str) -> str:
    pattern = re.compile(r"(https?://[^\s<]+)")
    escaped = escape(text)
    return pattern.sub(
        lambda match: f'<a href="{match.group(1)}" target="_blank" rel="noreferrer">{match.group(1)}</a>',
        escaped,
    )


def _markdown_to_html(text: str) -> str:
    blocks: list[str] = []
    bullet_buffer: list[str] = []

    def flush_bullets() -> None:
        if bullet_buffer:
            blocks.append("<ul>" + "".join(f"<li>{item}</li>" for item in bullet_buffer) + "</ul>")
            bullet_buffer.clear()

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            flush_bullets()
            continue
        if line.startswith("### "):
            flush_bullets()
            blocks.append(f"<h4>{_linkify(line[4:])}</h4>")
            continue
        if line.startswith("## "):
            flush_bullets()
            blocks.append(f"<h3>{_linkify(line[3:])}</h3>")
            continue
        if line.startswith("# "):
            flush_bullets()
            blocks.append(f"<h2>{_linkify(line[2:])}</h2>")
            continue
        if line.startswith("- "):
            bullet_buffer.append(_linkify(line[2:]))
            continue
        flush_bullets()
        if ": " in line and not line.startswith("http"):
            key, value = line.split(": ", 1)
            blocks.append(f"<p><strong>{escape(key)}:</strong> {_linkify(value)}</p>")
        else:
            blocks.append(f"<p>{_linkify(line)}</p>")
    flush_bullets()
    return "\n".join(blocks)


def _load_drafts(drafts_dir: Path) -> list[dict[str, str]]:
    drafts: list[dict[str, str]] = []
    for path in sorted(drafts_dir.glob("*.md"), reverse=True):
        content = path.read_text()
        title = next((line[2:].strip() for line in content.splitlines() if line.startswith("# ")), path.stem)
        drafts.append(
            {
                "date": path.stem,
                "title": title,
                "path": path.name,
                "html": _markdown_to_html(content),
            }
        )
    return drafts


def _shared_styles() -> str:
    return """
  <style>
    :root {
      --bg: #f5f1e8;
      --paper: #fffdf8;
      --ink: #16212b;
      --muted: #5b6470;
      --accent: #a33d2f;
      --accent-soft: #f3ddd7;
      --line: #d9d0c3;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, #f7e0cf 0, transparent 28%),
        radial-gradient(circle at top right, #dbe9e1 0, transparent 24%),
        var(--bg);
    }
    a { color: var(--accent); }
    .wrap {
      max-width: 1040px;
      margin: 0 auto;
      padding: 32px 20px 56px;
    }
    .hero, .panel {
      background: rgba(255, 253, 248, 0.88);
      border: 1px solid var(--line);
      border-radius: 24px;
      padding: 28px;
      backdrop-filter: blur(8px);
      box-shadow: 0 12px 30px rgba(22, 33, 43, 0.06);
    }
    .panel {
      margin-top: 22px;
      padding: 22px;
    }
    .eyebrow {
      display: inline-block;
      margin-bottom: 12px;
      padding: 6px 10px;
      background: var(--accent-soft);
      border-radius: 999px;
      font-size: 12px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }
    h1, h2, h3, h4 { margin: 0 0 12px; line-height: 1.08; }
    h1 { font-size: clamp(2.2rem, 4vw, 4.4rem); max-width: 12ch; }
    p { line-height: 1.6; }
    .muted, .subtext { color: var(--muted); }
    .stats {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 12px;
      margin-top: 24px;
    }
    .stat {
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 16px;
    }
    .stat-label {
      display: block;
      color: var(--muted);
      font-size: 13px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }
    .stat-value {
      display: block;
      margin-top: 8px;
      font-size: 32px;
      font-weight: 700;
    }
    .status-row, .nav {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 16px;
    }
    .chip, .nav a {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 10px;
      border-radius: 999px;
      background: #efe8dc;
      border: 1px solid var(--line);
      font-size: 12px;
      text-decoration: none;
    }
    .nav a.active {
      background: var(--accent);
      color: white;
      border-color: var(--accent);
    }
    .draft-list {
      display: grid;
      gap: 14px;
      margin-top: 12px;
    }
    .draft-card {
      border: 1px solid var(--line);
      border-radius: 18px;
      background: var(--paper);
      overflow: hidden;
    }
    .draft-card summary {
      cursor: pointer;
      list-style: none;
      display: flex;
      justify-content: space-between;
      gap: 16px;
      padding: 14px 16px;
      font-weight: 700;
    }
    .draft-card summary::-webkit-details-marker { display: none; }
    .draft-body {
      border-top: 1px solid var(--line);
      padding: 18px 16px 8px;
    }
    .draft-body ul { margin: 0 0 16px 18px; }
    .controls {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin: 12px 0 16px;
    }
    .controls input, .controls select {
      padding: 10px 12px;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: var(--paper);
      font: inherit;
      min-width: 180px;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }
    th, td {
      text-align: left;
      padding: 12px 10px;
      border-top: 1px solid var(--line);
      vertical-align: top;
    }
    th {
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }
    .hero-links {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-top: 18px;
    }
    .source-list {
      display: grid;
      gap: 10px;
      margin-top: 14px;
    }
    .source-item {
      padding: 14px 16px;
      border: 1px solid var(--line);
      border-radius: 16px;
      background: var(--paper);
    }
    .source-item strong {
      display: block;
      margin-bottom: 4px;
    }
    .hero-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 11px 16px;
      border-radius: 999px;
      border: 1px solid var(--ink);
      text-decoration: none;
      color: var(--ink);
      background: transparent;
    }
    .hero-link.primary {
      background: var(--accent);
      border-color: var(--accent);
      color: white;
    }
    @media (max-width: 980px) {
      table, thead, tbody, th, td, tr { display: block; }
      thead { display: none; }
      tr {
        border-top: 1px solid var(--line);
        padding: 12px 0;
      }
      td {
        border: 0;
        padding: 4px 0;
      }
    }
  </style>
"""


def _nav(active: str) -> str:
    archive_class = "active" if active == "archive" else ""
    items_class = "active" if active == "items" else ""
    return f"""
    <nav class="nav">
      <a class="{archive_class}" href="./index.html">Daily Digest Archive</a>
      <a class="{items_class}" href="./items.html">Historical Item Database</a>
    </nav>
    """


def _build_archive_page(
    drafts: list[dict[str, str]],
    by_category,
    by_status,
    generated_at: str,
) -> str:
    stats_html = "".join(
        f'<div class="stat"><span class="stat-label">{escape(row["category"].title())}</span>'
        f'<span class="stat-value">{row["count"]}</span></div>'
        for row in by_category
    )
    status_html = "".join(
        f'<span class="chip">{escape(row["status"])}: {row["count"]}</span>' for row in by_status
    )
    paper_source_html = """
      <div class="source-list">
        <div class="source-item">
          <strong>arXiv</strong>
          Preprints focused on cancer screening, liquid biopsy, and related AI methods.
        </div>
        <div class="source-item">
          <strong>PubMed</strong>
          Broad published-paper search covering early detection, screening, early diagnosis, and AI in cancer.
        </div>
        <div class="source-item">
          <strong>medRxiv</strong>
          Recent oncology preprints from medRxiv, filtered locally for AI and early cancer relevance.
        </div>
        <div class="source-item">
          <strong>Top journal watchlist via PubMed</strong>
          Targeted monitoring of Nature, Science, Cell, Lancet, JAMA, and selected subjournals including Nature Medicine, Nature Cancer, Nature Biomedical Engineering, Cancer Cell, Lancet Oncology, and JAMA Oncology.
        </div>
      </div>
    """
    funding_source_html = """
      <div class="source-list">
        <div class="source-item">
          <strong>Cancer Research UK News</strong>
          Cancer Research UK news feed, used as an early signal for relevant funding and researcher-facing announcements.
        </div>
        <div class="source-item">
          <strong>UKRI Opportunities</strong>
          Official UK Research and Innovation opportunities feed.
        </div>
        <div class="source-item">
          <strong>NIH Funding Opportunities</strong>
          Official NIH Guide for Grants and Contracts RSS feed.
        </div>
      </div>
    """
    job_source_html = """
      <div class="source-list">
        <div class="source-item">
          <strong>University of Cambridge Research Jobs</strong>
          Official Cambridge research-vacancies page.
        </div>
        <div class="source-item">
          <strong>jobs.ac.uk cancer and AI search</strong>
          Search-driven academic jobs board feed focused on cancer and AI keywords.
        </div>
        <div class="source-item">
          <strong>Manual watchlist</strong>
          Curated additions for roles we want to include before a dedicated scraper exists.
        </div>
      </div>
    """
    drafts_html = "".join(
        f"""
        <details class="draft-card" {"open" if index == 0 else ""}>
          <summary>
            <span>{escape(draft["date"])}</span>
            <span>{escape(draft["title"])}</span>
          </summary>
          <div class="draft-body">{draft["html"]}</div>
        </details>
        """
        for index, draft in enumerate(drafts)
    ) or "<p class='muted'>No drafts yet.</p>"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Cambridge AI for Early Cancer Digest</title>
{_shared_styles()}
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <span class="eyebrow">Cambridge-initiated digest</span>
      <h1>Daily Digest Archive</h1>
      <p class="muted">A public archive of the daily AI for early cancer digest. The most recent issue opens by default; older issues stay folded below.</p>
      {_nav("archive")}
      <div class="hero-links">
        <a class="hero-link primary" href="./items.html">Browse Historical Database</a>
      </div>
      <div class="stats">{stats_html}</div>
      <div class="status-row">{status_html}</div>
      <p class="muted">Last generated: {generated_at}</p>
    </section>

    <section class="panel">
      <h2>Paper Sources</h2>
      <p class="muted">Current paper monitoring combines preprint servers, published-paper databases, and a targeted top-journal watchlist.</p>
      {paper_source_html}
    </section>

    <section class="panel">
      <h2>Funding Sources</h2>
      <p class="muted">Funding opportunities currently come from official grant feeds and researcher-facing funding announcements.</p>
      {funding_source_html}
    </section>

    <section class="panel">
      <h2>Job Sources</h2>
      <p class="muted">Job opportunities combine official institutional pages, targeted academic search pages, and a small manual watchlist.</p>
      {job_source_html}
    </section>

    <section class="panel">
      <h2>Archive</h2>
      <p class="muted">Newest draft first.</p>
      <div class="draft-list">{drafts_html}</div>
    </section>
  </div>
</body>
</html>
"""


def _build_items_page(items, generated_at: str) -> str:
    rows_html = "".join(
        f"""
        <tr data-category="{escape(row['category'])}" data-status="{escape(row['status'])}">
          <td>{escape(_format_timestamp(row['display_date']))}</td>
          <td><span class="chip">{escape(row['category'])}</span></td>
          <td>{escape(row['source'])}</td>
          <td>
            <a href="{escape(row['url'])}" target="_blank" rel="noreferrer">{escape(row['title'])}</a>
            <div class="subtext">{escape((row['summary'] or '')[:220])}</div>
          </td>
          <td>{row['score']:.1f}</td>
          <td>{escape(row['status'])}</td>
        </tr>
        """
        for row in items
    ) or "<tr><td colspan='6'>No items yet.</td></tr>"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Historical Item Database | Cambridge AI for Early Cancer Digest</title>
{_shared_styles()}
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <span class="eyebrow">Cambridge-initiated digest</span>
      <h1>Historical Item Database</h1>
      <p class="muted">Search and filter historical papers, funding calls, and job opportunities collected by the digest pipeline.</p>
      {_nav("items")}
      <div class="hero-links">
        <a class="hero-link" href="./index.html">Back to Daily Digest Archive</a>
      </div>
      <p class="muted">Last generated: {generated_at}</p>
    </section>

    <section class="panel">
      <h2>Browse Items</h2>
      <div class="controls">
        <input id="search" type="search" placeholder="Search titles or sources">
        <select id="category">
          <option value="">All categories</option>
          <option value="paper">Papers</option>
          <option value="funding">Funding</option>
          <option value="job">Jobs</option>
        </select>
        <select id="status">
          <option value="">All statuses</option>
          <option value="new">new</option>
          <option value="reviewed">reviewed</option>
          <option value="drafted">drafted</option>
          <option value="approved">approved</option>
          <option value="sent">sent</option>
          <option value="rejected">rejected</option>
        </select>
      </div>
      <table>
        <thead>
          <tr>
            <th>Date</th>
            <th>Category</th>
            <th>Source</th>
            <th>Item</th>
            <th>Score</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody id="rows">
          {rows_html}
        </tbody>
      </table>
    </section>
  </div>
  <script>
    const search = document.getElementById('search');
    const category = document.getElementById('category');
    const status = document.getElementById('status');
    const rows = Array.from(document.querySelectorAll('#rows tr'));

    function applyFilters() {{
      const q = search.value.trim().toLowerCase();
      const c = category.value;
      const s = status.value;

      rows.forEach((row) => {{
        const text = row.innerText.toLowerCase();
        const show =
          (!q || text.includes(q)) &&
          (!c || row.dataset.category === c) &&
          (!s || row.dataset.status === s);
        row.style.display = show ? '' : 'none';
      }});
    }}

    search.addEventListener('input', applyFilters);
    category.addEventListener('change', applyFilters);
    status.addEventListener('change', applyFilters);
  </script>
</body>
</html>
"""


def build_site(db_path: Path, drafts_dir: Path, site_dir: Path) -> Path:
    site_dir.mkdir(parents=True, exist_ok=True)

    with connect(db_path) as conn:
        items = conn.execute(
            """
            SELECT id, title, source, category, status, score, summary, why_relevant, url,
                   COALESCE(published_at, fetched_at) AS display_date
            FROM items
            ORDER BY COALESCE(published_at, fetched_at) DESC, id DESC
            """
        ).fetchall()
        by_category = conn.execute(
            """
            SELECT category, COUNT(*) AS count
            FROM items
            GROUP BY category
            ORDER BY category
            """
        ).fetchall()
        by_status = conn.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM items
            GROUP BY status
            ORDER BY status
            """
        ).fetchall()

    drafts = _load_drafts(drafts_dir)
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    index_path = site_dir / "index.html"
    index_path.write_text(_build_archive_page(drafts, by_category, by_status, generated_at))
    (site_dir / "items.html").write_text(_build_items_page(items, generated_at))
    (site_dir / ".nojekyll").write_text("")
    return index_path
