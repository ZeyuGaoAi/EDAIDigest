from __future__ import annotations

import json
from copy import deepcopy
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote

from digest.config import DB_PATH, DRAFTS_DIR, REVIEW_QUEUE_PATH, SETTINGS_PATH, SITE_DIR, SOURCES_PATH
from digest.drafts import export_review_queue, generate_template_draft
from digest.fetch import ingest
from digest.settings import load_settings, lookback_days_from_settings, max_items_from_settings, min_scores_from_settings
from digest.site import build_site


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2) + "\n")
    tmp_path.replace(path)


def _save_settings_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("base"), dict) or not isinstance(payload.get("changes"), dict):
        raise ValueError("Outdated Setup page. Reload it before saving settings.")
    if "email_template" in payload["changes"]:
        raise ValueError("Email styling is maintained in the backend, not in Setup.")
    current = load_settings(SETTINGS_PATH)
    merged = deepcopy(current)

    def apply_changes(target: dict[str, Any], old: dict[str, Any], changes: dict[str, Any], path: str = "") -> None:
        for key, value in changes.items():
            field = f"{path}.{key}" if path else key
            previous = old.get(key)
            actual = target.get(key)
            if isinstance(value, dict) and isinstance(previous, dict) and isinstance(actual, dict):
                apply_changes(actual, previous, value, field)
            else:
                if actual != previous and actual != value:
                    raise ValueError(f"{field} changed since this page loaded. Reload Setup and try again.")
                target[key] = value

    apply_changes(merged, payload["base"], payload["changes"])
    if payload["changes"]:
        merged.pop("email_template", None)
        _write_json(SETTINGS_PATH, merged)
    return load_settings(SETTINGS_PATH)


def _save_sources_payload(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise ValueError("sources.json must be a JSON array")
    _write_json(SOURCES_PATH, payload)
    return payload


def _collect_candidates() -> dict[str, Any]:
    settings = load_settings(SETTINGS_PATH)
    lookback_days = lookback_days_from_settings(settings)
    min_scores = min_scores_from_settings(settings)
    stats, errors = ingest(DB_PATH, SOURCES_PATH)
    review_path = export_review_queue(DB_PATH, REVIEW_QUEUE_PATH, lookback_days, min_scores)
    site_path = build_site(DB_PATH, DRAFTS_DIR, SITE_DIR, SETTINGS_PATH, SOURCES_PATH)
    return {
        "review_queue": str(review_path),
        "site": str(site_path),
        "stats": stats,
        "errors": errors,
    }


def _generate_reviewed_digest() -> dict[str, Any]:
    settings = load_settings(SETTINGS_PATH)
    draft_path = generate_template_draft(
        DB_PATH,
        DRAFTS_DIR,
        lookback_days_from_settings(settings),
        min_scores_from_settings(settings),
        settings.get("email_template", {}),
        max_items_from_settings(settings),
        settings.get("distribution", {}).get("email_subject"),
        SOURCES_PATH,
        settings.get("email_copy"),
    )
    site_path = build_site(DB_PATH, DRAFTS_DIR, SITE_DIR, SETTINGS_PATH, SOURCES_PATH)
    return {
        "draft": str(draft_path),
        "site": str(site_path),
    }


def _latest_draft_stem() -> str:
    stems = sorted(
        {path.stem for path in DRAFTS_DIR.glob("*.html")}
        | {path.stem for path in DRAFTS_DIR.glob("*.txt")}
        | {path.stem for path in DRAFTS_DIR.glob("*.md")},
        reverse=True,
    )
    if not stems:
        settings = load_settings(SETTINGS_PATH)
        generate_template_draft(
            DB_PATH,
            DRAFTS_DIR,
            lookback_days_from_settings(settings),
            min_scores_from_settings(settings),
            settings.get("email_template", {}),
            max_items_from_settings(settings),
            settings.get("distribution", {}).get("email_subject"),
            SOURCES_PATH,
            settings.get("email_copy"),
        )
        stems = sorted({path.stem for path in DRAFTS_DIR.glob("*.html")} | {path.stem for path in DRAFTS_DIR.glob("*.txt")}, reverse=True)
    if not stems:
        raise ValueError("No digest draft exists yet")
    return stems[0]


def _latest_text_draft_path() -> Path:
    stem = _latest_draft_stem()
    for suffix in (".txt", ".md", ".html"):
        path = DRAFTS_DIR / f"{stem}{suffix}"
        if path.exists():
            return path
    raise ValueError("No digest draft exists yet")


def _latest_html_draft_path() -> Path:
    stem = _latest_draft_stem()
    path = DRAFTS_DIR / f"{stem}.html"
    if path.exists():
        return path
    settings = load_settings(SETTINGS_PATH)
    generate_template_draft(
        DB_PATH,
        DRAFTS_DIR,
        lookback_days_from_settings(settings),
        min_scores_from_settings(settings),
        settings.get("email_template", {}),
        max_items_from_settings(settings),
        settings.get("distribution", {}).get("email_subject"),
        SOURCES_PATH,
        settings.get("email_copy"),
    )
    path = DRAFTS_DIR / f"{_latest_draft_stem()}.html"
    if not path.exists():
        raise ValueError("No HTML digest draft exists yet")
    return path


def _latest_html_and_text_draft() -> tuple[Path, str, str]:
    html_path = _latest_html_draft_path()
    text_path = DRAFTS_DIR / f"{html_path.stem}.txt"
    text = text_path.read_text() if text_path.exists() else html_path.read_text()
    return html_path, html_path.read_text(), text


def _mailto_for_latest_draft(settings: dict[str, Any]) -> str:
    distribution = settings.get("distribution", {})
    recipients = distribution.get("recipient_emails", [])
    if not recipients:
        raise ValueError("Add at least one recipient email before preparing a draft")
    draft_path = _latest_text_draft_path()
    body = draft_path.read_text()
    date_slug = draft_path.stem
    subject_template = distribution.get("email_subject") or "AI for Early Cancer Digest | {date}"
    subject = subject_template.format(date=date_slug)
    to = ",".join(recipients)
    return f"mailto:{quote(to)}?subject={quote(subject)}&body={quote(body)}"


class SetupRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, directory=str(SITE_DIR), **kwargs)

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> Any:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        return json.loads(body.decode("utf-8"))

    def do_POST(self) -> None:
        try:
            if self.path == "/api/settings":
                payload = self._read_json_body()
                settings = _save_settings_payload(payload)
                build_site(DB_PATH, DRAFTS_DIR, SITE_DIR, SETTINGS_PATH, SOURCES_PATH)
                self._send_json(
                    HTTPStatus.OK,
                    {"message": "Saved to data/settings.json and rebuilt the setup page.", "settings": settings},
                )
                return

            if self.path == "/api/sources":
                payload = self._read_json_body()
                _save_sources_payload(payload)
                build_site(DB_PATH, DRAFTS_DIR, SITE_DIR, SETTINGS_PATH, SOURCES_PATH)
                self._send_json(
                    HTTPStatus.OK,
                    {"message": "Saved to data/sources.json and rebuilt the setup page."},
                )
                return

            if self.path == "/api/collect":
                payload = self._read_json_body()
                if isinstance(payload, dict):
                    if "settings" in payload:
                        _save_settings_payload(payload["settings"])
                    if "sources" in payload:
                        _save_sources_payload(payload["sources"])
                result = _collect_candidates()
                warning = ""
                if result["errors"]:
                    warning = " Some sources returned errors; see terminal output or review queue."
                self._send_json(
                    HTTPStatus.OK,
                    {
                        **result,
                        "message": f"Collected candidates for Codex review: {result['review_queue']}.{warning}",
                    },
                )
                return

            if self.path == "/api/generate-reviewed":
                payload = self._read_json_body()
                if isinstance(payload, dict) and "settings" in payload:
                    _save_settings_payload(payload["settings"])
                result = _generate_reviewed_digest()
                self._send_json(
                    HTTPStatus.OK,
                    {
                        **result,
                        "message": f"Generated digest from Codex-reviewed candidates: {result['draft']}",
                    },
                )
                return

            if self.path == "/api/html-draft":
                payload = self._read_json_body()
                if isinstance(payload, dict) and "settings" in payload:
                    _save_settings_payload(payload["settings"])
                    build_site(DB_PATH, DRAFTS_DIR, SITE_DIR, SETTINGS_PATH, SOURCES_PATH)
                draft_path, html, text = _latest_html_and_text_draft()
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "html": html,
                        "text": text,
                        "message": f"Opened rich HTML draft: {draft_path}. Copy the rendered content into your email composer.",
                    },
                )
                return

            if self.path == "/api/email-draft":
                payload = self._read_json_body()
                settings = load_settings(SETTINGS_PATH)
                if isinstance(payload, dict) and "settings" in payload:
                    settings = _save_settings_payload(payload["settings"])
                    build_site(DB_PATH, DRAFTS_DIR, SITE_DIR, SETTINGS_PATH, SOURCES_PATH)
                mailto = _mailto_for_latest_draft(settings)
                sender = settings.get("distribution", {}).get("sender_email", "your default mail account")
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "mailto": mailto,
                        "message": f"Opening email draft using the default mail client. Send from: {sender}.",
                    },
                )
                return

            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Unknown endpoint"})
        except Exception as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})


def serve_setup(host: str = "127.0.0.1", port: int = 8765) -> None:
    server = ThreadingHTTPServer((host, port), SetupRequestHandler)
    print(f"Serving setup editor at http://{host}:{port}/")
    print("Press Ctrl-C to stop.")
    server.serve_forever()
