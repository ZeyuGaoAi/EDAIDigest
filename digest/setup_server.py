from __future__ import annotations

import json
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from digest.config import DB_PATH, DRAFTS_DIR, SETTINGS_PATH, SITE_DIR, SOURCES_PATH
from digest.settings import load_settings
from digest.site import build_site


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2) + "\n")
    tmp_path.replace(path)


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
                if not isinstance(payload, dict):
                    raise ValueError("settings.json must be a JSON object")
                _write_json(SETTINGS_PATH, payload)
                load_settings(SETTINGS_PATH)
                build_site(DB_PATH, DRAFTS_DIR, SITE_DIR, SETTINGS_PATH, SOURCES_PATH)
                self._send_json(
                    HTTPStatus.OK,
                    {"message": "Saved to data/settings.json and rebuilt the setup page."},
                )
                return

            if self.path == "/api/sources":
                payload = self._read_json_body()
                if not isinstance(payload, list):
                    raise ValueError("sources.json must be a JSON array")
                _write_json(SOURCES_PATH, payload)
                build_site(DB_PATH, DRAFTS_DIR, SITE_DIR, SETTINGS_PATH, SOURCES_PATH)
                self._send_json(
                    HTTPStatus.OK,
                    {"message": "Saved to data/sources.json and rebuilt the setup page."},
                )
                return

            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Unknown endpoint"})
        except Exception as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})


def serve_setup(host: str = "127.0.0.1", port: int = 8765) -> None:
    build_site(DB_PATH, DRAFTS_DIR, SITE_DIR, SETTINGS_PATH, SOURCES_PATH)
    server = ThreadingHTTPServer((host, port), SetupRequestHandler)
    print(f"Serving setup editor at http://{host}:{port}/")
    print("Press Ctrl-C to stop.")
    server.serve_forever()
