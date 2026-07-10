from __future__ import annotations

import argparse
from pathlib import Path

from digest.config import DB_PATH, DRAFTS_DIR, REVIEW_QUEUE_PATH, SETTINGS_PATH, SITE_DIR, SOURCES_PATH
from digest.db import init_db
from digest.drafts import export_review_queue, generate_template_draft, set_status
from digest.fetch import ingest
from digest.settings import load_settings, lookback_days_from_settings, max_items_from_settings, min_scores_from_settings
from digest.site import build_site


def add_lookback_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--paper-days", type=int)
    parser.add_argument("--funding-days", type=int)
    parser.add_argument("--job-days", type=int)


def add_settings_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--settings", type=Path, default=SETTINGS_PATH)


def lookback_config(args: argparse.Namespace, settings: dict) -> dict[str, int]:
    config = lookback_days_from_settings(settings)
    for category in ("paper", "funding", "job"):
        value = getattr(args, f"{category}_days", None)
        if value is not None:
            config[category] = value
    return config


def min_score_config(args: argparse.Namespace, settings: dict) -> dict[str, float]:
    config = min_scores_from_settings(settings)
    min_score = getattr(args, "min_score", None)
    if min_score is not None:
        config = {category: min_score for category in ("paper", "funding", "job")}
    return config


def max_items_config(args: argparse.Namespace, settings: dict) -> dict[str, int]:
    config = max_items_from_settings(settings)
    per_category = getattr(args, "per_category", None)
    if per_category is not None:
        config = {category: per_category for category in ("paper", "funding", "job")}
    return config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI early cancer digest CLI")
    parser.add_argument("--db", type=Path, default=DB_PATH)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db")

    ingest_parser = subparsers.add_parser("ingest")
    ingest_parser.add_argument("--sources", type=Path, default=SOURCES_PATH)

    queue_parser = subparsers.add_parser("export-review")
    queue_parser.add_argument("--output", type=Path, default=REVIEW_QUEUE_PATH)
    add_settings_arg(queue_parser)
    add_lookback_args(queue_parser)
    queue_parser.add_argument("--min-score", type=float)

    draft_parser = subparsers.add_parser("generate-draft")
    draft_parser.add_argument("--drafts-dir", type=Path, default=DRAFTS_DIR)
    add_settings_arg(draft_parser)
    add_lookback_args(draft_parser)
    draft_parser.add_argument("--per-category", type=int)

    site_parser = subparsers.add_parser("build-site")
    site_parser.add_argument("--drafts-dir", type=Path, default=DRAFTS_DIR)
    site_parser.add_argument("--site-dir", type=Path, default=SITE_DIR)
    add_settings_arg(site_parser)
    site_parser.add_argument("--sources", type=Path, default=SOURCES_PATH)

    serve_parser = subparsers.add_parser("serve-setup")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)

    daily_parser = subparsers.add_parser(
        "run-digest",
        aliases=["run-daily"],
        help="Fetch sources, create the review queue and draft, then rebuild the site.",
    )
    daily_parser.add_argument("--sources", type=Path, default=SOURCES_PATH)
    add_settings_arg(daily_parser)
    daily_parser.add_argument("--review-output", type=Path, default=REVIEW_QUEUE_PATH)
    daily_parser.add_argument("--drafts-dir", type=Path, default=DRAFTS_DIR)
    daily_parser.add_argument("--site-dir", type=Path, default=SITE_DIR)
    add_lookback_args(daily_parser)
    daily_parser.add_argument("--min-score", type=float)
    daily_parser.add_argument("--per-category", type=int)

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
        settings = load_settings(args.settings)
        path = export_review_queue(
            args.db,
            args.output,
            lookback_config(args, settings),
            min_score_config(args, settings),
        )
        print(path)
        return 0

    if args.command == "generate-draft":
        settings = load_settings(args.settings)
        path = generate_template_draft(
            args.db,
            args.drafts_dir,
            lookback_config(args, settings),
            min_score_config(args, settings),
            settings.get("email_template", {}),
            max_items_config(args, settings),
            settings.get("distribution", {}).get("email_subject"),
        )
        print(path)
        return 0

    if args.command == "build-site":
        path = build_site(args.db, args.drafts_dir, args.site_dir, args.settings, args.sources)
        print(path)
        return 0

    if args.command == "serve-setup":
        from digest.setup_server import serve_setup

        serve_setup(args.host, args.port)
        return 0

    if args.command in {"run-digest", "run-daily"}:
        settings = load_settings(args.settings)
        stats, errors = ingest(args.db, args.sources)
        review_path = export_review_queue(
            args.db,
            args.review_output,
            lookback_config(args, settings),
            min_score_config(args, settings),
        )
        draft_path = generate_template_draft(
            args.db,
            args.drafts_dir,
            lookback_config(args, settings),
            min_score_config(args, settings),
            settings.get("email_template", {}),
            max_items_config(args, settings),
            settings.get("distribution", {}).get("email_subject"),
        )
        site_path = build_site(args.db, args.drafts_dir, args.site_dir, args.settings, args.sources)
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
