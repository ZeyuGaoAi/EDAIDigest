from datetime import UTC, datetime
import unittest

from digest.drafts import _category_filter_sql


class DraftDateWindowTests(unittest.TestCase):
    def test_includes_items_within_one_day_of_generation(self):
        now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
        _, params = _category_filter_sql(
            {"paper": 7, "funding": 30, "job": 30},
            now,
        )
        self.assertEqual(params[1], "2026-07-23T12:00:00+00:00")
        self.assertEqual(params[2], "2026-07-31T12:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
