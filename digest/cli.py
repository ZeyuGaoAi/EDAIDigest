from __future__ import annotations

import argparse
from pathlib import Path

from digest.config import DB_PATH, DRAFTS_DIR, REVIEW_QUEUE_PATH, SITE_DIR, SOURCES_PATH
from digest.db import init_db
from digest.drafts import export_review_queue, generate_template_draft, set_status
from digest.fetch import ingest
from digest.site import build_site


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI early cancer digest CLI")
    parser.add_argument("--db", type=Path, default=DB_PATH)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db")

    ingest_parser = subparsers.add_parser("ingest")
    ingest_parser.add_argument("--sources", type=Path, default=SOURCES_PATH)

    queue_parser = subparsers.add_parser("export-review")
    queue_parser.add_argument("--output", type=Path, default=REVIEW_QUEUE_PATH)
    queue_parser.add_argument("--lookback-days", type=int, default=7)
    queue_parser.add_argument("--min-score", type=float, default=3.5)

    draft_parser = subparsers.add_parser("generate-draft")
    draft_parser.add_argument("--drafts-dir", type=Path, default=DRAFTS_DIR)
    draft_parser.add_argument("--lookback-days", type=int, default=7)
    draft_parser.add_argument("--per-category", type=int, default=3)

    site_parser = subparsers.add_parser("build-site")
    site_parser.add_argument("--drafts-dir", type=Path, default=DRAFTS_DIR)
    site_parser.add_argument("--site-dir", type=Path, default=SITE_DIR)

    daily_parser = subparsers.add_parser("run-daily")
    daily_parser.add_argument("--sources", type=Path, default=SOURCES_PATH)
    daily_parser.add_argument("--review-output", type=Path, default=REVIEW_QUEUE_PATH)
    daily_parser.add_argument("--drafts-dir", type=Path, default=DRAFTS_DIR)
    daily_parser.add_argument("--site-dir", type=Path, default=SITE_DIR)
    daily_parser.add_argument("--lookback-days", type=int, default=7)
    daily_parser.add_argument("--min-score", type=float, default=3.5)
    daily_parser.add_argument("--per-category", type=int, default=3)

    status_parser = subparsers.add_parser("set-status")
    status_parser.add_argument("item_id", type=int)
    status_parser.add_argument("status")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "init-db":
        init_db(args.db)
        print(f"Initialized database at {args.db}")
        return 0

    init_db(args.db)

    if args.command == "ingest":
        stats, errors = ingest(args.db, args.sources)
        for source_name, count in stats.items():
            print(f"{source_name}: {count} items processed")
        for source_name, error in errors.items():
            print(f"{source_name}: ERROR {error}")
        return 0

    if args.command == "export-review":
        path = export_review_queue(args.db, args.output, args.lookback_days, args.min_score)
        print(path)
        return 0

    if args.command == "generate-draft":
        path = generate_template_draft(args.db, args.drafts_dir, args.lookback_days, args.per_category)
        print(path)
        return 0

    if args.command == "build-site":
        path = build_site(args.db, args.drafts_dir, args.site_dir)
        print(path)
        return 0

    if args.command == "run-daily":
        stats, errors = ingest(args.db, args.sources)
        review_path = export_review_queue(args.db, args.review_output, args.lookback_days, args.min_score)
        draft_path = generate_template_draft(args.db, args.drafts_dir, args.lookback_days, args.per_category)
        site_path = build_site(args.db, args.drafts_dir, args.site_dir)
        print("Ingest:")
        for source_name, count in stats.items():
            print(f"  {source_name}: {count} items processed")
        if errors:
            print("Errors:")
            for source_name, error in errors.items():
                print(f"  {source_name}: {error}")
        print(f"Review queue: {review_path}")
        print(f"Draft: {draft_path}")
        print(f"Site: {site_path}")
        return 0

    if args.command == "set-status":
        set_status(args.db, args.item_id, args.status)
        print(f"Item {args.item_id} set to {args.status}")
        return 0

    parser.error("Unknown command")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
