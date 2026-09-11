from datetime import UTC, datetime
import unittest

from digest.drafts import _category_filter_sql


class DraftDateWindowTests(unittest.TestCase):
    def test_includes_whole_calendar_days_at_the_window_boundaries(self):
        now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
        sql, params = _category_filter_sql(
            {"paper": 7, "funding": 30, "job": 30},
            now,
        )
        self.assertIn("date(COALESCE(published_at, fetched_at))", sql)
        self.assertEqual(params[1], "2026-07-23")
        self.assertEqual(params[2], "2026-07-30")


if __name__ == "__main__":
    unittest.main()
