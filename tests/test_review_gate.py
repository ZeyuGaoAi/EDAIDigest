from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from digest.db import connect, init_db
import digest.drafts as drafts


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 7, 31, 12, 0, tzinfo=UTC)


class ReviewGateTests(unittest.TestCase):
    def test_draft_uses_reviewed_items_and_leaves_new_candidates_out(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            db_path = root / "digest.db"
            init_db(db_path)
            with connect(db_path) as conn:
                for title, status in (("Reviewed paper", "reviewed"), ("New paper", "new")):
                    conn.execute(
                        """
                        INSERT INTO items (
                            url, title, source, venue, category, published_at, fetched_at,
                            status, score, summary, why_relevant, content_hash
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            f"https://example.test/{status}",
                            title,
                            "Test source",
                            "Test journal",
                            "paper",
                            "2026-07-31T10:00:00+00:00",
                            "2026-07-31T10:00:00+00:00",
                            status,
                            10.0,
                            "Early cancer screening with machine learning.",
                            "test",
                            status,
                        ),
                    )
                conn.commit()

            with patch.object(drafts, "datetime", FixedDatetime):
                path = drafts.generate_template_draft(db_path, root / "drafts")

            html = path.read_text()
            self.assertIn("Reviewed paper", html)
            self.assertNotIn("New paper", html)
            with connect(db_path) as conn:
                status = conn.execute(
                    "SELECT status FROM items WHERE title = 'Reviewed paper'"
                ).fetchone()["status"]
            self.assertEqual(status, "drafted")

    def test_configured_window_is_rendered_in_the_template(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            db_path = root / "digest.db"
            init_db(db_path)
            with patch.object(drafts, "datetime", FixedDatetime):
                path = drafts.generate_template_draft(
                    db_path,
                    root / "drafts",
                    {"paper": 14, "funding": 30, "job": 30},
                )

            self.assertIn("Papers cover the past 14 days", path.read_text())

    def test_draft_deduplicates_mirrored_opportunities_by_title(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            db_path = root / "digest.db"
            init_db(db_path)
            with connect(db_path) as conn:
                for source, title in (
                    ("Manchester ACED", "ACED Clinical Research Training Fellowship (2027)"),
                    ("Cambridge ACED", "ACED Clinical Research Training Fellowship 2027"),
                ):
                    conn.execute(
                        """
                        INSERT INTO items (
                            url, title, source, venue, category, published_at, fetched_at,
                            status, score, summary, why_relevant, content_hash
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            f"https://example.test/{source}", title, source, source, "funding",
                            "2026-07-31T10:00:00+00:00", "2026-07-31T10:00:00+00:00",
                            "reviewed", 10.0, "Cancer early detection funding.", "test", source,
                        ),
                    )
                conn.commit()

            with patch.object(drafts, "datetime", FixedDatetime):
                html = drafts.generate_template_draft(db_path, root / "drafts").read_text()

            self.assertEqual(html.count("ACED Clinical Research Training Fellowship"), 1)


if __name__ == "__main__":
    unittest.main()
