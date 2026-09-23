"""Mira must start a NEW idea — never reuse pending/old uploads/old remake topic."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from jarvis.mira.formats import looks_like_new_brief, parse_format_reply
from jarvis.mira.uploads import should_use_uploads
from jarvis.tools.mira_tool import parse_mira_command


class TopicSwitchTests(unittest.TestCase):
    def test_new_brief_not_format_reply(self):
        self.assertTrue(looks_like_new_brief("make a funny video about ocean waves"))
        self.assertIsNone(parse_format_reply("make a funny video about ocean waves"))
        # Real menu replies still work
        self.assertEqual(parse_format_reply("2")["format"], "youtube_shorts")
        self.assertEqual(parse_format_reply("shorts funny")["format"], "youtube_shorts")
        self.assertEqual(parse_format_reply("shorts funny")["mood"], "funny")

    def test_active_batch_does_not_hijack_new_topic(self):
        fake_batch = {"count": 3, "updated_at": 9_999_999_999, "paths": ["a.png"]}
        with patch("jarvis.mira.uploads.load_active_batch", return_value=fake_batch):
            with patch("jarvis.mira.uploads.has_uploads", return_value=True):
                self.assertFalse(should_use_uploads("make a video about coffee shops"))
                self.assertTrue(should_use_uploads("make a video using my uploads about nexus"))

    def test_parse_topic_b_after_topic_a(self):
        with patch("jarvis.mira.uploads.should_use_uploads", return_value=False):
            a = parse_mira_command("make a 12 second mute short about rainforest frogs")
            b = parse_mira_command("make a 12 second mute short about tokyo neon streets")
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        assert a and b
        self.assertIn("rainforest", a["topic"].lower())
        self.assertIn("tokyo", b["topic"].lower())
        self.assertNotEqual(a["topic"].lower(), b["topic"].lower())
        self.assertFalse(a.get("use_uploads"))
        self.assertFalse(b.get("use_uploads"))

    def test_pending_new_idea_clears(self):
        from jarvis.mira.session import clear_pending, save_pending
        from jarvis.tools.mira_tool import try_mira_command

        save_pending(
            {
                "action": "video",
                "topic": "old coffee shops",
                "format": "youtube_shorts",
                "needs_format": True,
            }
        )
        try:
            # Should NOT resume old coffee — new idea
            with patch("jarvis.tools.mira_tool.run_parsed_action", return_value="NEW") as run:
                with patch("jarvis.tools.mira_tool._visibility_gate", return_value=None):
                    out = try_mira_command(
                        "make a mute short about desert sand dunes",
                        background=False,
                    )
            # Either ran new action or returned None to fall through — never old topic
            if out == "NEW":
                args = run.call_args[0][0]
                self.assertIn("desert", str(args.get("topic") or "").lower())
                self.assertNotIn("coffee", str(args.get("topic") or "").lower())
        finally:
            clear_pending()


if __name__ == "__main__":
    unittest.main()
