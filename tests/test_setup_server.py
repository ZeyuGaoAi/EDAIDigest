from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from digest.settings import DEFAULT_EMAIL_TEMPLATE, load_settings
from digest.setup_server import _save_settings_payload
from digest.site import _build_archive_page, _build_config_editor


class SetupSettingsTests(unittest.TestCase):
    def test_setup_exposes_copy_but_not_html_styling(self):
        settings = load_settings(None)
        setup = _build_config_editor(settings, [])
        archive = _build_archive_page([], [], [], "now", settings, [])
        self.assertIn('id="email-intro"', setup)
        self.assertIn('id="recipient-emails"', setup)
        self.assertNotIn('id="body-template"', setup)
        self.assertNotIn("Email Body Template", archive)

    def test_editing_recipients_does_not_revert_email_layout(self):
        with TemporaryDirectory() as directory:
            settings_path = Path(directory) / "settings.json"
            base = load_settings(settings_path)
            old_page = deepcopy(base)
            old_page["email_template"]["body_template"] = "Stale plain template"
            update = {
                "base": old_page,
                "changes": {"distribution": {"recipient_emails": ["new@example.org"]}},
            }

            with patch("digest.setup_server.SETTINGS_PATH", settings_path):
                saved = _save_settings_payload(update)

            self.assertEqual(saved["distribution"]["recipient_emails"], ["new@example.org"])
            self.assertEqual(saved["email_template"], DEFAULT_EMAIL_TEMPLATE)
            self.assertNotIn("email_template", json.loads(settings_path.read_text()))

    def test_conflicting_copy_edit_requires_reload(self):
        with TemporaryDirectory() as directory:
            settings_path = Path(directory) / "settings.json"
            base = load_settings(settings_path)
            settings_path.write_text(json.dumps({"email_copy": {"intro": "Updated elsewhere"}}))
            with patch("digest.setup_server.SETTINGS_PATH", settings_path):
                with self.assertRaisesRegex(ValueError, "changed since this page loaded"):
                    _save_settings_payload({"base": base, "changes": {"email_copy": {"intro": "My edit"}}})

    def test_old_full_page_save_is_rejected(self):
        with TemporaryDirectory() as directory:
            settings_path = Path(directory) / "settings.json"
            with patch("digest.setup_server.SETTINGS_PATH", settings_path):
                with self.assertRaisesRegex(ValueError, "Outdated Setup page"):
                    _save_settings_payload(load_settings(settings_path))
            self.assertFalse(settings_path.exists())


if __name__ == "__main__":
    unittest.main()
