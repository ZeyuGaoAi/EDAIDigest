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

            self.assertIn("Published in the past 14 days", path.read_text())

    def test_email_layout_preserves_logo_and_emoji_sections(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            db_path = root / "digest.db"
            init_db(db_path)
            with patch.object(drafts, "datetime", FixedDatetime):
                path = drafts.generate_template_draft(db_path, root / "drafts")

            html = path.read_text()
            self.assertIn('<table role="presentation"', html)
            self.assertIn('<img src="https://esac-network.eu/', html)
            self.assertIn("🔬 Papers", html)
            self.assertIn("💡 Funding", html)
            self.assertIn("💼 Jobs", html)
            self.assertNotIn("&lt;table", html)

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
            with connect(db_path) as conn:
                statuses = [row["status"] for row in conn.execute("SELECT status FROM items")]
            self.assertEqual(statuses, ["drafted", "drafted"])

    def test_reviewed_low_score_paper_is_included_after_semantic_review(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            db_path = root / "digest.db"
            init_db(db_path)
            with connect(db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO items (
                        url, title, source, venue, category, published_at, fetched_at,
                        status, score, summary, why_relevant, content_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "https://example.test/trust", "Screening method", "Test source", "Test journal",
                        "paper", "2026-07-31T10:00:00+00:00", "2026-07-31T10:00:00+00:00",
                        "reviewed", 0.0, "A clinically targeted screening method.", "semantic review", "trust",
                    ),
                )

            with patch.object(drafts, "datetime", FixedDatetime):
                html = drafts.generate_template_draft(db_path, root / "drafts").read_text()

            self.assertIn("Screening method", html)

    def test_drafted_funding_and_jobs_repeat_within_their_window_but_papers_do_not(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            db_path = root / "digest.db"
            init_db(db_path)
            with connect(db_path) as conn:
                for category, title in (
                    ("paper", "Previously sent paper"),
                    ("funding", "Open early cancer funding"),
                    ("job", "Open early cancer job"),
                ):
                    conn.execute(
                        """
                        INSERT INTO items (
                            url, title, source, venue, category, published_at, fetched_at,
                            status, score, summary, why_relevant, content_hash
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            f"https://example.test/{category}", title, "Test source", "Test venue", category,
                            "2026-07-31T10:00:00+00:00", "2026-07-31T10:00:00+00:00",
                            "drafted", 10.0, "Cancer early detection opportunity.", "test", category,
                        ),
                    )

            with patch.object(drafts, "datetime", FixedDatetime):
                html = drafts.generate_template_draft(db_path, root / "drafts").read_text()

            self.assertNotIn("Previously sent paper", html)
            self.assertIn("Open early cancer funding", html)
            self.assertIn("Open early cancer job", html)


if __name__ == "__main__":
    unittest.main()
