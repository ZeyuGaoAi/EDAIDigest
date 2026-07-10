from __future__ import annotations

from datetime import UTC, datetime
from html import escape
from html import unescape
import json
from pathlib import Path
import re

from digest.db import connect
from digest.settings import load_settings


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


def _clean_text(text: str | None, limit: int = 220) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"<[^>]+>", " ", unescape(text))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 3].rstrip()}..."


def _load_sources(path: Path) -> list[dict]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text())
    if not isinstance(payload, list):
        raise ValueError(f"Sources file must contain a JSON list: {path}")
    return payload


def _json_for_html(payload) -> str:
    return escape(json.dumps(payload, indent=2))


def _json_for_script(payload) -> str:
    return json.dumps(payload, indent=2).replace("<", "\\u003c").replace(">", "\\u003e")


def _source_detail(source: dict) -> str:
    kind = source.get("kind", "rss")
    if kind == "pubmed":
        detail = f"PubMed query, retmax {source.get('retmax', 20)}."
    elif kind == "biorxiv_api":
        detail = f"{source.get('server', 'bioRxiv')} API, recent {source.get('recent_days', 'configured')} days."
    elif kind == "html_links":
        detail = f"HTML link scraper: {source.get('url', 'configured URL')}."
    elif kind == "manual":
        detail = f"Manual file: {source.get('path', 'configured path')}."
    else:
        detail = f"RSS/feed source: {source.get('url', 'configured URL')}."
    if "priority" in source:
        detail += f" Digest priority {source['priority']}."
    if "max_digest_items" in source:
        detail += f" Digest cap {source['max_digest_items']}."
    return detail


def _sources_html(sources: list[dict], category: str) -> str:
    rows = []
    for source in sources:
        if source.get("category") != category:
            continue
        rows.append(
            f"""
            <div class="source-item">
              <strong>{escape(source.get("name", "Unnamed source"))}</strong>
              {escape(_source_detail(source))}
            </div>
            """
        )
    return '<div class="source-list">' + "".join(rows) + "</div>"


def _settings_value(settings: dict, path: tuple[str, ...], default: str = ""):
    value = settings
    for key in path:
        if not isinstance(value, dict):
            return default
        value = value.get(key)
    return default if value is None else value


def _clean_generated_html(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.splitlines()) + "\n"


def _build_config_editor(settings: dict, sources: list[dict]) -> str:
    cards = []
    for category, label in (("paper", "Papers"), ("funding", "Funding"), ("job", "Jobs")):
        lookback_days = escape(str(_settings_value(settings, ("cadence", category, "lookback_days"))))
        frequency = escape(str(_settings_value(settings, ("cadence", category, "frequency"))))
        min_score = escape(str(_settings_value(settings, ("cadence", category, "min_score"))))
        max_items = escape(str(_settings_value(settings, ("cadence", category, "max_items"), 5)))
        scope = escape(str(_settings_value(settings, ("scope", category))))
        cards.append(
            f"""
            <div class="config-card" data-category="{category}">
              <h3>{label}</h3>
              <label for="{category}-days">Lookback Days</label>
              <input id="{category}-days" data-field="lookback_days" type="number" min="1" step="1" value="{lookback_days}">
              <label for="{category}-frequency">Update Frequency</label>
              <input id="{category}-frequency" data-field="frequency" value="{frequency}">
              <label for="{category}-score">Minimum Score</label>
              <input id="{category}-score" data-field="min_score" type="number" min="0" step="0.1" value="{min_score}">
              <label for="{category}-max-items">Max Items in Digest</label>
              <input id="{category}-max-items" data-field="max_items" type="number" min="1" step="1" value="{max_items}">
              <label for="{category}-scope">Scope</label>
              <textarea id="{category}-scope" data-scope="{category}">{scope}</textarea>
            </div>
            """
        )

    workflow_trigger = escape(str(_settings_value(settings, ("workflow", "trigger"))))
    workflow_review = escape(str(_settings_value(settings, ("workflow", "review"))))
    body_template = escape(str(_settings_value(settings, ("email_template", "body_template"))))
    paper_template = escape(str(_settings_value(settings, ("email_template", "item_templates", "paper"))))
    funding_template = escape(str(_settings_value(settings, ("email_template", "item_templates", "funding"))))
    job_template = escape(str(_settings_value(settings, ("email_template", "item_templates", "job"))))
    sender_email = escape(str(_settings_value(settings, ("distribution", "sender_email"))))
    recipient_emails = _settings_value(settings, ("distribution", "recipient_emails"), [])
    recipient_text = escape("\n".join(recipient_emails if isinstance(recipient_emails, list) else []))
    email_subject = escape(str(_settings_value(settings, ("distribution", "email_subject"))))

    return f"""
      <div class="config-grid">
        {''.join(cards)}
      </div>

      <div class="config-grid">
        <div class="config-card">
          <h3>Workflow</h3>
          <label for="workflow-trigger">Trigger</label>
          <input id="workflow-trigger" value="{workflow_trigger}">
          <label for="workflow-review">Review</label>
          <input id="workflow-review" value="{workflow_review}">
        </div>
      </div>

      <label for="body-template">Email Body Template</label>
      <p class="muted">Available placeholders: {{date}}, {{subject}}, {{paper_days}}, {{funding_days}}, {{job_days}}, {{papers}}, {{funding}}, {{jobs}}, {{sources}}.</p>
      <textarea id="body-template" class="json-editor">{body_template}</textarea>

      <div class="config-grid">
        <div class="config-card">
          <h3>Paper Item Template</h3>
          <textarea id="paper-item-template" class="json-editor">{paper_template}</textarea>
        </div>
        <div class="config-card">
          <h3>Funding Item Template</h3>
          <textarea id="funding-item-template" class="json-editor">{funding_template}</textarea>
        </div>
        <div class="config-card">
          <h3>Job Item Template</h3>
          <textarea id="job-item-template" class="json-editor">{job_template}</textarea>
        </div>
      </div>

      <label for="sources-json">Sources JSON</label>
      <textarea id="sources-json" class="json-editor">{_json_for_html(sources)}</textarea>

      <div class="config-grid">
        <div class="config-card">
          <h3>Email Distribution</h3>
          <label for="sender-email">Sender Email</label>
          <input id="sender-email" value="{sender_email}">
          <label for="recipient-emails">Recipient Emails</label>
          <textarea id="recipient-emails">{recipient_text}</textarea>
          <label for="email-subject">Email Subject</label>
          <input id="email-subject" value="{email_subject}">
        </div>
      </div>

      <div class="button-row">
        <button id="save-settings" type="button">Save settings.json</button>
        <button id="save-sources" type="button">Save sources.json</button>
        <button id="regenerate-digest" type="button">Regenerate Weekly Digest</button>
        <button id="open-html-draft" type="button">Open HTML Draft</button>
        <button id="copy-rich-email" type="button">Copy Rich Email</button>
        <button id="open-email-draft" type="button">Open Email Draft</button>
        <button id="save-browser-draft" class="secondary" type="button">Save Browser Draft</button>
        <button id="reset-browser-draft" class="secondary" type="button">Reset Draft</button>
      </div>
      <p id="config-status" class="status-line">Local setup server saves directly to data/. Static GitHub Pages falls back to downloading JSON files.</p>
      <script type="application/json" id="settings-json-data">{_json_for_script(settings)}</script>
      <script>
        const settingsSeed = JSON.parse(document.getElementById('settings-json-data').textContent);
        const sourceEditor = document.getElementById('sources-json');
        const configStatus = document.getElementById('config-status');

        function collectSettings() {{
          const next = JSON.parse(JSON.stringify(settingsSeed));
          next.cadence = next.cadence || {{}};
          next.scope = next.scope || {{}};
          document.querySelectorAll('.config-card[data-category]').forEach((card) => {{
            const category = card.dataset.category;
            next.cadence[category] = next.cadence[category] || {{}};
            card.querySelectorAll('[data-field]').forEach((input) => {{
              const field = input.dataset.field;
              next.cadence[category][field] = field === 'frequency' ? input.value.trim() : Number(input.value);
            }});
            const scope = card.querySelector('[data-scope]');
            next.scope[category] = scope.value.trim();
          }});
          next.workflow = {{
            trigger: document.getElementById('workflow-trigger').value.trim(),
            review: document.getElementById('workflow-review').value.trim(),
          }};
          next.email_template = {{
            body_template: document.getElementById('body-template').value.trim(),
            item_templates: {{
              paper: document.getElementById('paper-item-template').value.trim(),
              funding: document.getElementById('funding-item-template').value.trim(),
              job: document.getElementById('job-item-template').value.trim(),
            }},
          }};
          next.distribution = {{
            sender_email: document.getElementById('sender-email').value.trim(),
            recipient_emails: document.getElementById('recipient-emails').value
              .split(/[\\n,;]/)
              .map((email) => email.trim())
              .filter(Boolean),
            email_subject: document.getElementById('email-subject').value.trim(),
          }};
          return next;
        }}

        function applySettingsDraft(draft) {{
          document.querySelectorAll('.config-card[data-category]').forEach((card) => {{
            const category = card.dataset.category;
            const cadence = (draft.cadence && draft.cadence[category]) || {{}};
            card.querySelectorAll('[data-field]').forEach((input) => {{
              const field = input.dataset.field;
              if (cadence[field] !== undefined) {{
                input.value = cadence[field];
              }}
            }});
            const scope = card.querySelector('[data-scope]');
            if (draft.scope && draft.scope[category] !== undefined) {{
              scope.value = draft.scope[category];
            }}
          }});
          if (draft.workflow) {{
            document.getElementById('workflow-trigger').value = draft.workflow.trigger || '';
            document.getElementById('workflow-review').value = draft.workflow.review || '';
          }}
          if (draft.email_template) {{
            document.getElementById('body-template').value = draft.email_template.body_template || '';
            const itemTemplates = draft.email_template.item_templates || {{}};
            document.getElementById('paper-item-template').value = itemTemplates.paper || '';
            document.getElementById('funding-item-template').value = itemTemplates.funding || '';
            document.getElementById('job-item-template').value = itemTemplates.job || '';
          }}
          if (draft.distribution) {{
            document.getElementById('sender-email').value = draft.distribution.sender_email || '';
            document.getElementById('recipient-emails').value = (draft.distribution.recipient_emails || []).join('\\n');
            document.getElementById('email-subject').value = draft.distribution.email_subject || '';
          }}
        }}

        function parseSources() {{
          const parsed = JSON.parse(sourceEditor.value);
          if (!Array.isArray(parsed)) {{
            throw new Error('sources.json must be a JSON array');
          }}
          return parsed;
        }}

        function downloadJson(filename, payload) {{
          const blob = new Blob([JSON.stringify(payload, null, 2) + '\\n'], {{ type: 'application/json' }});
          const url = URL.createObjectURL(blob);
          const link = document.createElement('a');
          link.href = url;
          link.download = filename;
          link.click();
          URL.revokeObjectURL(url);
        }}

        async function saveJson(filename, payload) {{
          const endpoint = filename === 'settings.json' ? '/api/settings' : '/api/sources';
          try {{
            const response = await fetch(endpoint, {{
              method: 'POST',
              headers: {{ 'Content-Type': 'application/json' }},
              body: JSON.stringify(payload),
            }});
            if (response.ok) {{
              const result = await response.json();
              localStorage.removeItem('edaidigest.settingsDraft');
              localStorage.removeItem('edaidigest.sourcesDraft');
              configStatus.textContent = result.message || `Saved ${{filename}}.`;
              return;
            }}
            if (![404, 405, 501].includes(response.status)) {{
              const result = await response.json().catch(() => ({{ error: response.statusText }}));
              configStatus.textContent = result.error || `Save failed with HTTP ${{response.status}}.`;
              return;
            }}
          }} catch (error) {{
            // Static hosts do not expose the local save API; download remains the fallback.
          }}

          const text = JSON.stringify(payload, null, 2) + '\\n';
          if ('showSaveFilePicker' in window) {{
            try {{
              const handle = await window.showSaveFilePicker({{
                suggestedName: filename,
                types: [{{ description: 'JSON', accept: {{ 'application/json': ['.json'] }} }}],
              }});
              const writable = await handle.createWritable();
              await writable.write(text);
              await writable.close();
              configStatus.textContent = `Saved ${{filename}} locally. Start the setup server for automatic data/ writes.`;
              return;
            }} catch (error) {{
              if (error.name === 'AbortError') {{
                configStatus.textContent = 'Save cancelled.';
                return;
              }}
            }}
          }}
          downloadJson(filename, payload);
          configStatus.textContent = `Downloaded ${{filename}}. Start python3 -m digest.cli serve-setup for automatic data/ writes.`;
        }}

        async function postJson(endpoint, payload) {{
          if (!['127.0.0.1', 'localhost'].includes(window.location.hostname)) {{
            throw new Error('This action requires the local setup server. Open http://127.0.0.1:8765/setup.html.');
          }}
          const response = await fetch(endpoint, {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify(payload),
          }});
          const result = await response.json().catch(() => ({{ error: response.statusText }}));
          if (!response.ok) {{
            throw new Error(result.error || `HTTP ${{response.status}}`);
          }}
          return result;
        }}

        async function fetchHtmlDraft() {{
          return postJson('/api/html-draft', {{
            settings: collectSettings(),
          }});
        }}

        document.getElementById('save-settings').addEventListener('click', async () => {{
          await saveJson('settings.json', collectSettings());
        }});

        document.getElementById('save-sources').addEventListener('click', async () => {{
          try {{
            await saveJson('sources.json', parseSources());
          }} catch (error) {{
            configStatus.textContent = error.message;
          }}
        }});

        document.getElementById('regenerate-digest').addEventListener('click', async () => {{
          try {{
            configStatus.textContent = 'Regenerating weekly digest...';
            const result = await postJson('/api/regenerate', {{
              settings: collectSettings(),
              sources: parseSources(),
            }});
            configStatus.textContent = result.message;
            window.location.href = `./index.html?updated=${{Date.now()}}`;
          }} catch (error) {{
            configStatus.textContent = error.message;
          }}
        }});

        document.getElementById('open-email-draft').addEventListener('click', async () => {{
          try {{
            configStatus.textContent = 'Preparing email draft...';
            const result = await postJson('/api/email-draft', {{
              settings: collectSettings(),
            }});
            configStatus.textContent = result.message;
            window.location.href = result.mailto;
          }} catch (error) {{
            configStatus.textContent = error.message;
          }}
        }});

        document.getElementById('open-html-draft').addEventListener('click', async () => {{
          try {{
            configStatus.textContent = 'Preparing rich HTML draft...';
            const result = await fetchHtmlDraft();
            const blob = new Blob([result.html], {{ type: 'text/html' }});
            const url = URL.createObjectURL(blob);
            window.open(url, '_blank', 'noopener');
            configStatus.textContent = result.message;
          }} catch (error) {{
            configStatus.textContent = error.message;
          }}
        }});

        document.getElementById('copy-rich-email').addEventListener('click', async () => {{
          try {{
            configStatus.textContent = 'Copying rich email draft...';
            const result = await fetchHtmlDraft();
            if (navigator.clipboard && window.ClipboardItem) {{
              await navigator.clipboard.write([
                new ClipboardItem({{
                  'text/html': new Blob([result.html], {{ type: 'text/html' }}),
                  'text/plain': new Blob([result.text || result.html], {{ type: 'text/plain' }}),
                }}),
              ]);
              configStatus.textContent = 'Copied rich HTML email. Paste into your email composer to keep formatting.';
              return;
            }}
            if (navigator.clipboard && navigator.clipboard.writeText) {{
              await navigator.clipboard.writeText(result.text || result.html);
              configStatus.textContent = 'Copied plain-text fallback. This browser does not support rich HTML clipboard writes.';
              return;
            }}
            throw new Error('Clipboard API is not available in this browser.');
          }} catch (error) {{
            configStatus.textContent = error.message;
          }}
        }});

        document.getElementById('save-browser-draft').addEventListener('click', () => {{
          try {{
            localStorage.setItem('edaidigest.settingsDraft', JSON.stringify(collectSettings()));
            localStorage.setItem('edaidigest.sourcesDraft', sourceEditor.value);
            configStatus.textContent = 'Browser draft saved locally.';
          }} catch (error) {{
            configStatus.textContent = error.message;
          }}
        }});

        document.getElementById('reset-browser-draft').addEventListener('click', () => {{
          localStorage.removeItem('edaidigest.settingsDraft');
          localStorage.removeItem('edaidigest.sourcesDraft');
          configStatus.textContent = 'Browser draft cleared. Reload to restore committed values.';
        }});

        const settingsDraft = localStorage.getItem('edaidigest.settingsDraft');
        const sourcesDraft = localStorage.getItem('edaidigest.sourcesDraft');
        if (settingsDraft) {{
          try {{
            applySettingsDraft(JSON.parse(settingsDraft));
          }} catch (error) {{
            configStatus.textContent = error.message;
          }}
        }}
        if (sourcesDraft) {{
          sourceEditor.value = sourcesDraft;
          configStatus.textContent = 'Loaded browser draft. Save JSON files to use these values in future runs.';
        }}
      </script>
    """


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


def _html_title(text: str, fallback: str) -> str:
    match = re.search(r"<h1[^>]*>(.*?)</h1>", text, re.IGNORECASE | re.DOTALL)
    if not match:
        match = re.search(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
    if not match:
        return fallback
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", match.group(1)))).strip() or fallback


def _html_body_fragment(text: str) -> str:
    match = re.search(r"<body[^>]*>(.*?)</body>", text, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else text


def _load_drafts(drafts_dir: Path) -> list[dict[str, str]]:
    drafts: list[dict[str, str]] = []
    stems = sorted({path.stem for path in drafts_dir.glob("*.md")} | {path.stem for path in drafts_dir.glob("*.html")}, reverse=True)
    for stem in stems:
        html_path = drafts_dir / f"{stem}.html"
        md_path = drafts_dir / f"{stem}.md"
        path = html_path if html_path.exists() else md_path
        content = path.read_text()
        if path.suffix == ".html":
            title = _html_title(content, path.stem)
            html = _html_body_fragment(content)
        else:
            title = next((line[2:].strip() for line in content.splitlines() if line.startswith("# ")), path.stem)
            html = _markdown_to_html(content)
        drafts.append(
            {
                "date": path.stem,
                "title": title,
                "path": path.name,
                "html": html,
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
    .template-block {
      margin: 0;
      padding: 16px;
      border: 1px solid var(--line);
      border-radius: 16px;
      background: var(--paper);
      white-space: pre-wrap;
      font: 13px/1.55 "Courier New", Courier, monospace;
    }
    .config-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 14px;
      margin-top: 14px;
    }
    .config-card {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--paper);
      padding: 14px;
    }
    label {
      display: block;
      color: var(--muted);
      font-size: 12px;
      letter-spacing: 0.06em;
      margin: 12px 0 6px;
      text-transform: uppercase;
    }
    input, textarea {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fffdf8;
      color: var(--ink);
      font: inherit;
      padding: 9px 10px;
    }
    textarea {
      min-height: 88px;
      resize: vertical;
    }
    .json-editor {
      min-height: 260px;
      font: 13px/1.45 "Courier New", Courier, monospace;
    }
    .button-row {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 14px;
    }
    button {
      border: 1px solid var(--ink);
      border-radius: 999px;
      background: var(--ink);
      color: white;
      cursor: pointer;
      font: inherit;
      padding: 9px 14px;
    }
    button.secondary {
      background: transparent;
      color: var(--ink);
    }
    .status-line {
      min-height: 22px;
      color: var(--muted);
      font-size: 13px;
      margin-top: 10px;
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
    setup_class = "active" if active == "setup" else ""
    items_class = "active" if active == "items" else ""
    return f"""
    <nav class="nav">
      <a class="{archive_class}" href="./index.html">Daily Digest Archive</a>
      <a class="{setup_class}" href="./setup.html">Setup</a>
      <a class="{items_class}" href="./items.html">Historical Item Database</a>
    </nav>
    """


def _build_archive_page(
    drafts: list[dict[str, str]],
    by_category,
    by_status,
    generated_at: str,
    settings: dict,
    sources: list[dict],
) -> str:
    stats_html = "".join(
        f'<div class="stat"><span class="stat-label">{escape(row["category"].title())}</span>'
        f'<span class="stat-value">{row["count"]}</span></div>'
        for row in by_category
    )
    status_html = "".join(
        f'<span class="chip">{escape(row["status"])}: {row["count"]}</span>' for row in by_status
    )
    paper_source_html = _sources_html(sources, "paper")
    funding_source_html = _sources_html(sources, "funding")
    job_source_html = _sources_html(sources, "job")
    cadence = settings.get("cadence", {})
    scope = settings.get("scope", {})
    workflow = settings.get("workflow", {})
    email_template = settings.get("email_template", {})
    workflow_html = """
      <div class="source-list">
        <div class="source-item">
          <strong>Paper definition</strong>
          {paper_scope}
        </div>
        <div class="source-item">
          <strong>Funding definition</strong>
          {funding_scope}
        </div>
        <div class="source-item">
          <strong>Job definition</strong>
          {job_scope}
        </div>
      </div>
    """.format(
        paper_scope=escape(scope.get("paper", "")),
        funding_scope=escape(scope.get("funding", "")),
        job_scope=escape(scope.get("job", "")),
    )
    cadence_html = """
      <div class="source-list">
        <div class="source-item">
          <strong>Papers</strong>
          Search window: past {paper_days} days. Intended update rhythm: {paper_frequency}.
        </div>
        <div class="source-item">
          <strong>Funding</strong>
          Search window: past {funding_days} days. Intended update rhythm: {funding_frequency}.
        </div>
        <div class="source-item">
          <strong>Jobs</strong>
          Search window: past {job_days} days. Intended update rhythm: {job_frequency}.
        </div>
        <div class="source-item">
          <strong>Workflow</strong>
          {workflow_trigger} {workflow_review}
        </div>
      </div>
    """.format(
        paper_days=escape(str(_settings_value(settings, ("cadence", "paper", "lookback_days"), 7))),
        paper_frequency=escape(str(_settings_value(settings, ("cadence", "paper", "frequency"), "weekly"))),
        funding_days=escape(str(_settings_value(settings, ("cadence", "funding", "lookback_days"), 30))),
        funding_frequency=escape(str(_settings_value(settings, ("cadence", "funding", "frequency"), "monthly"))),
        job_days=escape(str(_settings_value(settings, ("cadence", "job", "lookback_days"), 30))),
        job_frequency=escape(str(_settings_value(settings, ("cadence", "job", "frequency"), "monthly"))),
        workflow_trigger=escape(workflow.get("trigger", "")),
        workflow_review=escape(workflow.get("review", "")),
    )
    configured_item_templates = email_template.get("item_templates", {})
    template_html = f"""Email body template:
{email_template.get("body_template", "")}

Paper item template:
{configured_item_templates.get("paper", "")}

Funding item template:
{configured_item_templates.get("funding", "")}

Job item template:
{configured_item_templates.get("job", "")}"""
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
      <p class="muted">A lightweight backup of generated AI for early cancer digest drafts. The most recent issue opens by default.</p>
      {_nav("archive")}
      <div class="hero-links">
        <a class="hero-link primary" href="./setup.html">Open Setup</a>
        <a class="hero-link primary" href="./items.html">Browse Historical Database</a>
      </div>
      <div class="stats">{stats_html}</div>
      <div class="status-row">{status_html}</div>
      <p class="muted">Last generated: {generated_at}</p>
    </section>

    <section class="panel">
      <h2>Scope Definition</h2>
      <p class="muted">The current setup keeps three item types and a deliberately short review workflow.</p>
      {workflow_html}
    </section>

    <section class="panel">
      <h2>Update Cadence</h2>
      <p class="muted">Papers are reviewed on a weekly window; funding and jobs stay broader and slower.</p>
      {cadence_html}
    </section>

    <section class="panel">
      <h2>Email Body Template</h2>
      <p class="muted">Current draft structure for reviewer-facing email generation.</p>
      <pre class="template-block">{escape(template_html)}</pre>
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
      <h2>Digest Archive</h2>
      <p class="muted">Newest draft first. The most recent issue opens by default.</p>
      <div class="draft-list">{drafts_html}</div>
    </section>
  </div>
</body>
</html>
"""


def _build_setup_page(settings: dict, sources: list[dict], generated_at: str) -> str:
    config_editor_html = _build_config_editor(settings, sources)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Setup | Cambridge AI for Early Cancer Digest</title>
{_shared_styles()}
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <span class="eyebrow">Cambridge-initiated digest</span>
      <h1>Setup</h1>
      <p class="muted">Edit cadence, source definitions, email template, distribution list, and manual actions for the digest pipeline.</p>
      {_nav("setup")}
      <div class="hero-links">
        <a class="hero-link primary" href="./index.html">Back to Digest Archive</a>
      </div>
      <p class="muted">Last generated: {generated_at}</p>
    </section>

    <section class="panel">
      <h2>Editable Configuration</h2>
      <p class="muted">Changes save directly to data/ when this page is served through the local setup server.</p>
      {config_editor_html}
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
            <div class="subtext">{escape(_clean_text(row['summary']))}</div>
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
          <option value="expired">expired</option>
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


def build_site(
    db_path: Path,
    drafts_dir: Path,
    site_dir: Path,
    settings_path: Path,
    sources_path: Path,
) -> Path:
    site_dir.mkdir(parents=True, exist_ok=True)
    settings = load_settings(settings_path)
    sources = _load_sources(sources_path)

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
    index_path.write_text(
        _clean_generated_html(_build_archive_page(drafts, by_category, by_status, generated_at, settings, sources))
    )
    (site_dir / "setup.html").write_text(_clean_generated_html(_build_setup_page(settings, sources, generated_at)))
    (site_dir / "items.html").write_text(_clean_generated_html(_build_items_page(items, generated_at)))
    (site_dir / "settings.json").write_text(json.dumps(settings, indent=2) + "\n")
    (site_dir / "sources.json").write_text(json.dumps(sources, indent=2) + "\n")
    (site_dir / ".nojekyll").write_text("")
    return index_path
