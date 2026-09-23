"""Unit tests: API hunt routing + .env save gate (no live browser, no secrets)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis.tools.api_intent import is_api_hunt_intent, wants_env_save
from jarvis.tools import api_registry


class WantsEnvSaveTests(unittest.TestCase):
    def test_positive_phrases(self):
        positives = [
            "save it to env",
            "save groq api to .env",
            "put it in .env",
            "post that api into .env",
            "write it to env",
            "add it to env",
            "save to .env",
            "write groq key to .env",
            "post groq api into env",
        ]
        for p in positives:
            self.assertTrue(wants_env_save(p), p)

    def test_negative_default_hunt(self):
        negatives = [
            "get me groq api key",
            "get eleven labs api key",
            "get api from https://console.groq.com/keys",
            "refresh groq api",
            "get all apis from sheet",
            "paste apis into sheet",
        ]
        for n in negatives:
            self.assertFalse(wants_env_save(n), n)


class HuntIntentPhase1Tests(unittest.TestCase):
    def test_hunts_never_miss_phase1(self):
        commands = [
            "get me groq api key",
            "get eleven labs api key",
            "get api from https://console.groq.com/keys",
            "save groq api to .env",
            "put fish api in .env",
        ]
        for c in commands:
            self.assertTrue(is_api_hunt_intent(c), c)

    def test_non_api_not_hunt(self):
        self.assertFalse(is_api_hunt_intent("what time is it"))
        self.assertFalse(is_api_hunt_intent("open youtube"))


class RegistryEnvGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.reg = root / "api_registry.json"
        self.env = root / ".env"
        self.env.write_text("JARVIS_EMAIL=test@example.com\n", encoding="utf-8")
        self._p_reg = patch.object(api_registry, "REGISTRY_PATH", self.reg)
        self._p_env = patch.object(api_registry, "ENV_PATH", self.env)
        self._p_reg.start()
        self._p_env.start()

    def tearDown(self):
        self._p_reg.stop()
        self._p_env.stop()
        self.tmp.cleanup()

    def test_save_key_default_skips_env(self):
        api_registry.save_key("groq", "gsk_test_fake_key_not_real_123456", "GROQ_API_KEY")
        env_text = self.env.read_text(encoding="utf-8")
        self.assertNotIn("GROQ_API_KEY", env_text)
        data = json.loads(self.reg.read_text(encoding="utf-8"))
        self.assertEqual(data["providers"]["groq"]["key"], "gsk_test_fake_key_not_real_123456")

    def test_save_key_write_env_true(self):
        api_registry.save_key(
            "groq",
            "gsk_test_fake_key_not_real_123456",
            "GROQ_API_KEY",
            write_env=True,
        )
        env_text = self.env.read_text(encoding="utf-8")
        self.assertIn("GROQ_API_KEY=gsk_test_fake_key_not_real_123456", env_text)

    def test_write_key_to_env_promotes_registry(self):
        api_registry.save_key("groq", "gsk_test_fake_key_not_real_123456", "GROQ_API_KEY")
        written = api_registry.write_key_to_env("groq")
        self.assertEqual(written, "GROQ_API_KEY")
        self.assertIn("GROQ_API_KEY=", self.env.read_text(encoding="utf-8"))


class FastRouterEnvGateTests(unittest.TestCase):
    def test_get_groq_chat_only_when_cached(self):
        from jarvis.fast_router import try_fast_command

        fake = "gsk_test_fake_key_not_real_abcdef"
        with patch("jarvis.tools.api_hunter.get_key", return_value=fake), patch(
            "jarvis.tools.api_hunter.save_key"
        ) as mock_save, patch(
            "jarvis.tools.api_hunter.write_key_to_env"
        ) as mock_write:
            resp = try_fast_command("get me groq api key")
            self.assertIsNotNone(resp)
            self.assertIn(fake, resp)
            self.assertNotIn("Saved to .env", resp)
            mock_write.assert_not_called()
            # registry update only, no env
            mock_save.assert_called()
            kwargs = mock_save.call_args.kwargs
            self.assertFalse(kwargs.get("write_env", False))

    def test_save_groq_to_env_writes(self):
        from jarvis.fast_router import try_fast_command

        fake = "gsk_test_fake_key_not_real_abcdef"
        with patch("jarvis.tools.api_hunter.get_key", return_value=fake), patch(
            "jarvis.tools.api_hunter.save_key"
        ), patch(
            "jarvis.tools.api_hunter.write_key_to_env", return_value="GROQ_API_KEY"
        ) as mock_write:
            resp = try_fast_command("save groq api to .env")
            self.assertIsNotNone(resp)
            self.assertIn("Saved", resp)
            self.assertIn("GROQ_API_KEY", resp)
            mock_write.assert_called()


if __name__ == "__main__":
    unittest.main()
