from __future__ import annotations

import plistlib
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from digest.friday import eligible_issue, launch_agent_data, run


class FridayLauncherTests(unittest.TestCase):
    def test_only_friday_after_nine_london_time_is_eligible(self) -> None:
        london = ZoneInfo("Europe/London")
        self.assertIsNone(eligible_issue(datetime(2026, 11, 6, 8, 59, tzinfo=london)))
        self.assertEqual(eligible_issue(datetime(2026, 11, 6, 9, tzinfo=london)), "2026-11-06")
        self.assertIsNone(eligible_issue(datetime(2026, 11, 7, 10, tzinfo=london)))

    def test_agent_runs_on_login_and_friday_morning(self) -> None:
        agent = plistlib.loads(launch_agent_data("/usr/bin/python3", Path("/tmp/digest")))
        self.assertTrue(agent["RunAtLoad"])
        self.assertEqual(agent["StartCalendarInterval"],
                         {"Weekday": 5, "Hour": 9, "Minute": 0})
        self.assertEqual(agent["ProgramArguments"][:2], ["/bin/bash", "-c"])
        self.assertIn("Terminal", agent["ProgramArguments"][2])
        self.assertIn("TZ=Europe/London", agent["ProgramArguments"][2])
        self.assertEqual(agent["WorkingDirectory"], "/tmp")
        self.assertNotIn("PYTHONPATH", agent["EnvironmentVariables"])

    def test_existing_friday_marker_prevents_duplicate_update(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "site-updated-2026-11-06").touch()
            with patch("digest.friday.ROOT", root), patch("digest.friday.STATE_DIR", root), \
                 patch("digest.friday.subprocess.run") as generate:
                run(datetime(2026, 11, 6, 9, tzinfo=ZoneInfo("Europe/London")))
            generate.assert_not_called()

    def test_successful_run_marks_site_updated_without_opening_mail(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "drafts").mkdir()
            (root / "docs").mkdir()
            (root / "drafts" / "2026-11-06.html").write_text("<p>Digest</p>")
            (root / "docs" / "index.html").write_text("2026-11-06")
            with patch("digest.friday.ROOT", root), patch("digest.friday.STATE_DIR", root), \
                 patch("digest.friday.DRAFTS_DIR", root / "drafts"), \
                 patch("digest.friday.subprocess.run") as generate, \
                 patch("digest.friday.notify"):
                generate.return_value.returncode = 0
                run(datetime(2026, 11, 6, 9, tzinfo=ZoneInfo("Europe/London")))
            self.assertTrue((root / "site-updated-2026-11-06").exists())
            self.assertEqual(generate.call_count, 1)


if __name__ == "__main__":
    unittest.main()
