from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DRAFTS_DIR = ROOT / "drafts"
SITE_DIR = ROOT / "site"
DB_PATH = DATA_DIR / "digest.db"
SOURCES_PATH = DATA_DIR / "sources.json"
REVIEW_QUEUE_PATH = ROOT / "review_queue.md"
