"""Uploads must not hijack unrelated Mira asks."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from jarvis.mira.uploads import should_use_uploads, wants_user_media
from jarvis.tools.mira_tool import parse_mira_command


class UploadsGateTests(unittest.TestCase):
    def test_stock_ask_ignores_old_folder_uploads(self):
        with patch("jarvis.mira.uploads.load_active_batch", return_value=None):
            with patch("jarvis.mira.uploads.recent_uploads", return_value=[{"path": "x.png"}]):
                with patch("jarvis.mira.uploads.has_uploads", return_value=True):
                    self.assertFalse(should_use_uploads("make a video about coffee shops"))

    def test_explicit_uploads_phrase(self):
        self.assertTrue(wants_user_media("make a mute short using my uploads"))
        self.assertTrue(should_use_uploads("make a video using my uploads about nexus"))

    def test_parse_stock_only(self):
        with patch("jarvis.mira.uploads.should_use_uploads", return_value=False):
            p = parse_mira_command("make a 12 second video about ocean waves stock only")
        self.assertIsNotNone(p)
        assert p is not None
        self.assertEqual(p["action"], "video")
        self.assertTrue("ocean" in p["topic"].lower() or "wave" in p["topic"].lower())
        self.assertFalse(p.get("use_uploads"))


if __name__ == "__main__":
    unittest.main()
