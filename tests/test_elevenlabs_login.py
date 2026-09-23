"""Mocked ElevenLabs / Clerk login — no live browser, no real secrets."""

from __future__ import annotations

import re
import unittest
from unittest.mock import patch

from jarvis.tools import api_hunter as hunter
from jarvis.tools.api_hunter import (
    EMAIL_SELECTORS,
    PASSWORD_SELECTORS,
    _action_name_re,
    _click_login_action,
    _do_login,
    _email_already_filled,
    _fill_email,
    _fill_password,
    _login_elevenlabs,
)


class FakeLoc:
    def __init__(self, page: "FakePage", kind: str, name: str = ""):
        self.page = page
        self.kind = kind
        self.name = name
        self.first = self

    def is_visible(self, timeout: int = 0) -> bool:
        if self.kind == "email":
            return self.page.step in ("email",)
        if self.kind == "password":
            return self.page.step == "password"
        if self.kind == "captcha":
            return False
        if self.kind == "button":
            return self.page.button_shown(self.name)
        if self.kind == "account":
            return False
        if self.kind == "placeholder":
            return False
        return False

    def get_attribute(self, attr: str):
        if self.kind == "email":
            return {"type": "email", "name": "identifier", "autocomplete": "email"}.get(attr, "")
        if self.kind == "password":
            return {"type": "password", "name": "password", "autocomplete": "current-password"}.get(attr, "")
        return ""

    def input_value(self, timeout: int = 0) -> str:
        if self.kind == "email":
            return self.page.email_value
        if self.kind == "password":
            return self.page.password_value
        return ""

    def click(self, timeout: int = 0) -> None:
        self.page.clicks.append(self.name or self.kind)
        if self.kind == "button":
            self.page.handle_click(self.name)

    def fill(self, value: str, timeout: int = 0) -> None:
        if self.kind == "email":
            self.page.email_value = value
            if value:
                self.page.email_fills.append(value)
        elif self.kind == "password":
            self.page.password_value = value
            if value:
                self.page.password_fills.append(value)
        else:
            raise AssertionError(f"fill on unexpected {self.kind}")

    def inner_text(self, timeout: int = 0) -> str:
        return self.name

    def fill_placeholder(self, value: str, timeout: int = 0) -> None:
        raise RuntimeError("no placeholder")


class FakeKeyboard:
    def __init__(self, page: "FakePage"):
        self.page = page

    def press(self, key: str) -> None:
        self.page.clicks.append(f"key:{key}")
        if key == "Enter":
            self.page.handle_click("Continue" if self.page.step == "email" else "Next")


class _FakePopupWait:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    @property
    def value(self):
        raise RuntimeError("no popup")


class FakePage:
    """Clerk-style: landing → email → (optionally stay on email) → password."""

    def __init__(self, *, sticky_email: int = 1, google: bool = True, email_entry: bool = True):
        self.url = "https://elevenlabs.io/sign-in"
        self.step = "landing"
        self.email_value = ""
        self.password_value = ""
        self.email_fills: list[str] = []
        self.password_fills: list[str] = []
        self.clicks: list[str] = []
        self.sticky_email = sticky_email  # Continues needed before password
        self.continues = 0
        self.google = google
        self.email_entry = email_entry
        self.keyboard = FakeKeyboard(self)
        self.context = self

    @property
    def pages(self):
        return [self]

    def expect_popup(self, timeout: int = 0):
        return _FakePopupWait()

    def bring_to_front(self) -> None:
        return None

    def goto(self, url: str, **kwargs) -> None:
        self.url = url
        if "accounts.google" in url or "myaccount.google" in url:
            self.step = "email"
            self.email_value = ""
            self.password_value = ""


    def button_shown(self, name: str) -> bool:
        n = name.lower()
        if self.step == "landing":
            if "google" in n:
                return self.google
            if not self.email_entry:
                return False
            return n in ("sign in with email", "continue with email", "use email")
        if self.step == "email":
            if n == "continue with google":
                return True  # bait: substring Continue used to hit this
            return n in ("continue", "next", "continue with email")
        if self.step == "password":
            return n in ("sign in", "log in", "continue", "next", "submit")
        return False

    def handle_click(self, name: str) -> None:
        n = (name or "").lower()
        if n == "continue with google" or n == "sign in with google":
            # Stay on ElevenLabs (SSO did not navigate)
            return
        if n in ("sign in with email", "continue with email", "use email", "log in with email"):
            if self.step == "landing":
                self.step = "email"
                return
            if n == "continue with email" and self.step == "email":
                self.continues += 1
                if self.continues > self.sticky_email:
                    self.step = "password"
                return
            return
        if n in ("continue", "next") and self.step == "email":
            self.continues += 1
            if self.continues > self.sticky_email:
                self.step = "password"
            return
        if n in ("sign in", "log in", "continue", "submit") and self.step == "password":
            self.url = "https://elevenlabs.io/app/home"
            self.step = "app"

    def locator(self, sel: str) -> FakeLoc:
        if sel in EMAIL_SELECTORS or "email" in sel.lower() or "identifier" in sel.lower():
            return FakeLoc(self, "email")
        if sel in PASSWORD_SELECTORS or "password" in sel.lower():
            return FakeLoc(self, "password")
        if "captcha" in sel.lower() or "recaptcha" in sel.lower() or "hcaptcha" in sel.lower():
            return FakeLoc(self, "captcha")
        return FakeLoc(self, "missing")

    def get_by_role(self, role: str, name=None) -> FakeLoc:
        label = name.pattern if hasattr(name, "pattern") else str(name or "")
        candidates = [
            "Continue with Google",
            "Sign in with Google",
            "Sign in with email",
            "Continue with email",
            "Use email",
            "Continue",
            "Next",
            "Sign in",
            "Log in",
            "Submit",
        ]
        for cand in candidates:
            if name is not None and name.search(cand):
                return FakeLoc(self, "button", cand)
        return FakeLoc(self, "button", label)

    def get_by_text(self, pattern) -> FakeLoc:
        return FakeLoc(self, "account")

    def get_by_placeholder(self, pattern) -> FakeLoc:
        return FakeLoc(self, "placeholder")

    def get_by_label(self, pattern) -> FakeLoc:
        return FakeLoc(self, "missing")

    def wait_for_timeout(self, ms: int) -> None:
        return None

    def wait_for_load_state(self, *a, **k) -> None:
        return None


class ExactContinueTests(unittest.TestCase):
    def test_continue_regex_does_not_match_google(self):
        exact = re.compile(r"^Continue$", re.I)
        self.assertTrue(exact.search("Continue"))
        self.assertFalse(exact.search("Continue with Google"))
        self.assertFalse(exact.search("Continue with email"))
        sign = re.compile(r"^Sign in$", re.I)
        self.assertFalse(sign.search("Sign in with email"))
        self.assertTrue(sign.search("Sign in"))

    def test_action_re_allows_continue_with_email_not_google(self):
        cont = _action_name_re("Continue")
        self.assertTrue(cont.search("Continue"))
        self.assertTrue(cont.search("Continue with email"))
        self.assertFalse(cont.search("Continue with Google"))
        sign = _action_name_re("Sign in")
        self.assertTrue(sign.search("Sign in"))
        self.assertTrue(sign.search("Sign in with email"))
        self.assertFalse(sign.search("Sign in with Google"))

    def test_click_login_skips_google_continue(self):
        page = FakePage()
        page.step = "email"
        self.assertTrue(_click_login_action(page, ["Continue"]))
        self.assertTrue(any(c.lower() in ("continue", "continue with email") for c in page.clicks))
        self.assertNotIn("Continue with Google", page.clicks)


class EmailFillGuardTests(unittest.TestCase):
    def test_skip_refill_when_email_already_correct(self):
        page = FakePage()
        page.step = "email"
        page.email_value = "ibrahim@example.com"
        self.assertTrue(_email_already_filled(page, "ibrahim@example.com"))
        self.assertTrue(_fill_email(page, "ibrahim@example.com"))
        self.assertEqual(page.email_fills, [])

    def test_password_refused_on_email_step(self):
        page = FakePage()
        page.step = "email"
        self.assertFalse(_fill_password(page, "not-a-real-password"))
        self.assertEqual(page.password_fills, [])

    def test_email_refused_on_password_step(self):
        page = FakePage()
        page.step = "password"
        self.assertFalse(_fill_email(page, "ibrahim@example.com"))
        self.assertEqual(page.email_fills, [])

    def test_password_only_goes_to_password_field(self):
        page = FakePage()
        page.step = "password"
        self.assertTrue(_fill_password(page, "not-a-real-password"))
        self.assertEqual(page.password_fills, ["not-a-real-password"])
        self.assertEqual(page.email_fills, [])


class ElevenLabsFlowTests(unittest.TestCase):
    def setUp(self):
        self._wait = patch.object(hunter, "_safe_wait", lambda *a, **k: None)
        self._wait.start()
        self._warm = patch.object(hunter, "_ensure_google_session", return_value="ok")
        self._warm.start()
        self._goto = patch.object(hunter, "_goto_login", lambda *a, **k: None)
        self._goto.start()

    def tearDown(self):
        self._wait.stop()
        self._warm.stop()
        self._goto.stop()

    def test_does_not_loop_email_when_already_filled(self):
        page = FakePage(sticky_email=0)
        page.step = "email"
        page.email_value = "ibrahim@example.com"
        with patch.object(hunter, "_progress"), patch.object(hunter, "_try_google_sso", return_value="skipped"):
            out = _login_elevenlabs(page, "ibrahim@example.com", "not-a-real-password", wait_sec=0)
        self.assertEqual(out, "ok")
        self.assertEqual(page.email_fills, [])
        self.assertEqual(page.password_fills, ["not-a-real-password"])
        self.assertNotIn("Continue with Google", page.clicks)

    def test_second_continue_without_third_email_fill(self):
        page = FakePage(sticky_email=1, google=False)
        with patch.object(hunter, "_progress"), patch.object(hunter, "_try_google_sso", return_value="skipped"):
            out = _login_elevenlabs(page, "ibrahim@example.com", "not-a-real-password", wait_sec=0)
        self.assertEqual(out, "ok")
        self.assertLessEqual(len([v for v in page.email_fills if v]), 2)
        self.assertEqual(page.password_fills, ["not-a-real-password"])
        self.assertEqual(page.step, "app")

    def test_stuck_email_after_max_fills(self):
        page = FakePage(sticky_email=99, google=False)
        with patch.object(hunter, "_progress"), patch.object(hunter, "_try_google_sso", return_value="skipped"):
            out = _login_elevenlabs(page, "ibrahim@example.com", "not-a-real-password", wait_sec=0)
        self.assertEqual(out, "stuck_email")
        self.assertLessEqual(len(page.email_fills), 2)
        self.assertEqual(page.password_fills, [])

    def test_do_login_routes_elevenlabs(self):
        page = FakePage(sticky_email=0, google=False)
        page.step = "email"
        page.email_value = "ibrahim@example.com"
        with patch.object(hunter, "_progress"), patch.object(hunter, "_dismiss_popups"), patch.object(
            hunter, "_try_google_sso", return_value="skipped"
        ):
            out = _do_login(page, "ibrahim@example.com", "not-a-real-password", "elevenlabs", wait_sec=0)
        self.assertEqual(out, "ok")

    def test_google_sso_first_for_elevenlabs(self):
        page = FakePage(sticky_email=0, google=True)
        with patch.object(hunter, "_progress"), patch.object(
            hunter, "_try_google_sso", return_value="ok"
        ) as google:
            out = _login_elevenlabs(page, "itsjarvisofficial1@gmail.com", "secret", wait_sec=0)
        self.assertEqual(out, "ok")
        google.assert_called_once()
        self.assertEqual(page.email_fills, [])  # never use site email/password

    def test_fills_email_when_google_skipped(self):
        page = FakePage(sticky_email=0, google=True)
        with patch.object(hunter, "_progress"), patch.object(
            hunter, "_try_google_sso", return_value="skipped"
        ):
            out = _login_elevenlabs(page, "ibrahim@example.com", "not-a-real-password", wait_sec=0)
        self.assertEqual(out, "ok")
        self.assertEqual(page.email_fills, ["ibrahim@example.com"])
        self.assertEqual(page.password_fills, ["not-a-real-password"])

    def test_continue_with_email_opens_then_submits(self):
        page = FakePage(sticky_email=0, google=False)
        page.email_entry = True

        def shown(name: str) -> bool:
            n = name.lower()
            if page.step == "landing":
                return n == "continue with email"
            if page.step == "email":
                return n in ("continue with email", "continue")
            if page.step == "password":
                return n in ("sign in", "log in")
            return False

        page.button_shown = shown  # type: ignore[method-assign]
        with patch.object(hunter, "_progress"), patch.object(
            hunter, "_try_google_sso", return_value="skipped"
        ):
            out = _login_elevenlabs(page, "ibrahim@example.com", "not-a-real-password", wait_sec=0)
        self.assertEqual(out, "ok")
        self.assertEqual(page.email_fills, ["ibrahim@example.com"])
        self.assertNotIn("Continue with Google", page.clicks)

    def test_google_fallback_only_when_email_field_missing(self):
        page = FakePage(sticky_email=0, google=True, email_entry=False)
        notes: list[str] = []
        with patch.object(hunter, "_progress", side_effect=lambda m: notes.append(m)):
            out = _login_elevenlabs(page, "ibrahim@example.com", "not-a-real-password", wait_sec=0)
        # Google-first; FakePage never completes Google → sso_blocked
        self.assertIn(out, ("sso_blocked", "challenge", "password_failed"))
        self.assertEqual(page.email_fills, [])
        self.assertTrue(
            any("google" in n.lower() for n in notes)
            or "Continue with Google" in page.clicks
        )


if __name__ == "__main__":
    unittest.main()
