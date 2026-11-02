from __future__ import annotations

import plistlib
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from digest.friday import ESAC_LOGO_URL, eligible_issue, launch_agent_data, prepare_compose_html, run


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
        self.assertEqual(agent["ProgramArguments"][-2:], ["digest.friday", "run"])

    def test_compose_copy_uses_cached_logo(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            draft = directory / "draft.html"
            output = directory / "compose.html"
            logo = directory / "logo.png"
            draft.write_text(f'<img src="{ESAC_LOGO_URL}"><strong>Digest</strong>')
            logo.write_bytes(b"\x89PNG\r\n\x1a\n")
            prepare_compose_html(draft, output, logo)
            self.assertIn(f'src="{logo.as_uri()}"', output.read_text())
            self.assertIn("<strong>Digest</strong>", output.read_text())
            self.assertIn(ESAC_LOGO_URL, draft.read_text())

    def test_existing_friday_marker_prevents_duplicate_compose(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "data").mkdir()
            (root / "data" / ".friday-mail-opened-2026-11-06").touch()
            with patch("digest.friday.ROOT", root), patch("digest.friday.STATE_DIR", root), \
                 patch("digest.friday.open_outlook_draft") as compose:
                run(datetime(2026, 11, 6, 9, tzinfo=ZoneInfo("Europe/London")))
            compose.assert_not_called()


if __name__ == "__main__":
    unittest.main()
