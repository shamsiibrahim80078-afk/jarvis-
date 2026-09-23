"""Google SSO auth loop — must reach password, never bounce on email label."""

from __future__ import annotations

import re
import unittest
from unittest.mock import patch

from jarvis.tools import api_hunter as hunter
from jarvis.tools.api_hunter import (
    EMAIL_SELECTORS,
    PASSWORD_SELECTORS,
    _complete_google_auth,
    _pick_google_account,
)


class FakeGoogleLoc:
    def __init__(self, page: "FakeGooglePage", kind: str, name: str = ""):
        self.page = page
        self.kind = kind
        self.name = name
        self.first = self

    def is_visible(self, timeout: int = 0) -> bool:
        if self.kind == "email":
            return self.page.step == "email"
        if self.kind == "password":
            return self.page.step == "password"
        if self.kind == "button":
            return self.page.button_shown(self.name)
        if self.kind == "account_tile":
            return self.page.step == "chooser"
        if self.kind == "email_label":
            # BUG repro: email text visible on password page too
            return self.page.step in ("chooser", "password", "email")
        if self.kind == "chooser_heading":
            return self.page.step == "chooser"
        if self.kind == "captcha":
            return False
        return False

    def get_attribute(self, attr: str):
        if self.kind == "email":
            return {"type": "email", "name": "identifier", "autocomplete": "username"}.get(attr, "")
        if self.kind == "password":
            return {"type": "password", "name": "Passwd", "autocomplete": "current-password"}.get(attr, "")
        if self.kind == "account_tile" and attr in ("data-identifier", "data-email"):
            return self.page.email
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
        elif self.kind == "account_tile":
            self.page.step = "password"
            self.page.url = "https://accounts.google.com/v3/signin/challenge/pwd"
            self.page.account_picks += 1
        elif self.kind == "email_label":
            # Bad old behavior: bounce to identifier
            self.page.step = "email"
            self.page.url = "https://accounts.google.com/v3/signin/identifier"
            self.page.email_bounces += 1

    def fill(self, value: str, timeout: int = 0) -> None:
        if self.kind == "email":
            self.page.email_value = value
            if value:
                self.page.email_fills.append(value)
        elif self.kind == "password":
            self.page.password_value = value
            if value:
                self.page.password_fills.append(value)

    def press_sequentially(self, value: str, delay: int = 0) -> None:
        self.fill(value)

    def press(self, key: str) -> None:
        self.page.clicks.append(f"key:{key}")
        if key == "Enter":
            self.page.handle_click("Next" if self.page.step == "email" else "Next")


class FakeGoogleKeyboard:
    def __init__(self, page: "FakeGooglePage"):
        self.page = page

    def press(self, key: str) -> None:
        self.page.clicks.append(f"key:{key}")
        if key == "Enter":
            self.page.handle_click("Next")


class FakeGooglePage:
    def __init__(self, *, start: str = "email", email: str = "itsjarvisofficial1@gmail.com"):
        self.email = email
        self.email_value = ""
        self.password_value = ""
        self.email_fills: list[str] = []
        self.password_fills: list[str] = []
        self.clicks: list[str] = []
        self.account_picks = 0
        self.email_bounces = 0
        self.keyboard = FakeGoogleKeyboard(self)
        self.context = self
        self.step = start
        if start == "email":
            self.url = "https://accounts.google.com/v3/signin/identifier"
        elif start == "chooser":
            self.url = "https://accounts.google.com/AccountChooser"
        elif start == "password":
            self.url = "https://accounts.google.com/v3/signin/challenge/pwd"
        else:
            self.url = "https://accounts.google.com/"

    @property
    def pages(self):
        return [self]

    def button_shown(self, name: str) -> bool:
        n = name.lower()
        if self.step == "email":
            return n in ("next", "continue")
        if self.step == "password":
            return n in ("next", "continue", "sign in")
        if self.step == "chooser":
            return n in ("next", "continue")
        return False

    def handle_click(self, name: str) -> None:
        n = (name or "").lower()
        if n in ("next", "continue") and self.step == "email":
            self.step = "password"
            self.url = "https://accounts.google.com/v3/signin/challenge/pwd"
            return
        if n in ("next", "continue", "sign in") and self.step == "password":
            if self.password_value:
                self.step = "done"
                self.url = "https://myaccount.google.com/"
            return

    def locator(self, sel: str) -> FakeGoogleLoc:
        sl = sel.lower()
        if "data-identifier" in sl or "data-email" in sl:
            return FakeGoogleLoc(self, "account_tile", "tile")
        if sel in EMAIL_SELECTORS or "email" in sl or "identifier" in sl:
            return FakeGoogleLoc(self, "email")
        if sel in PASSWORD_SELECTORS or "password" in sl or "passwd" in sl:
            return FakeGoogleLoc(self, "password")
        if "captcha" in sl:
            return FakeGoogleLoc(self, "captcha")
        return FakeGoogleLoc(self, "missing")

    def get_by_role(self, role: str, name=None) -> FakeGoogleLoc:
        label = name.pattern if hasattr(name, "pattern") else str(name or "")
        for cand in ("Next", "Continue", "Sign in", "Allow", "Accept", "Confirm"):
            if name is not None and name.search(cand):
                return FakeGoogleLoc(self, "button", cand)
        return FakeGoogleLoc(self, "button", label)

    def get_by_text(self, pattern) -> FakeGoogleLoc:
        pat = pattern.pattern if hasattr(pattern, "pattern") else str(pattern)
        if re.search(r"choose an account|select an account", pat, re.I):
            return FakeGoogleLoc(self, "chooser_heading")
        if self.email.lower() in pat.lower() or "itsjarvis" in pat.lower():
            return FakeGoogleLoc(self, "email_label", self.email)
        return FakeGoogleLoc(self, "missing")

    def get_by_placeholder(self, pattern) -> FakeGoogleLoc:
        return FakeGoogleLoc(self, "missing")

    def get_by_label(self, pattern) -> FakeGoogleLoc:
        return FakeGoogleLoc(self, "missing")

    def wait_for_timeout(self, ms: int) -> None:
        return None


class GoogleAuthLoopTests(unittest.TestCase):
    def setUp(self):
        self._wait = patch.object(hunter, "_safe_wait", lambda *a, **k: None)
        self._wait.start()
        self._prog = patch.object(hunter, "_progress", lambda *a, **k: None)
        self._prog.start()

    def tearDown(self):
        self._wait.stop()
        self._prog.stop()

    def test_password_page_does_not_click_email_label(self):
        page = FakeGooglePage(start="password")
        self.assertFalse(_pick_google_account(page, page.email))
        self.assertEqual(page.email_bounces, 0)
        self.assertEqual(page.account_picks, 0)

    def test_email_then_password_no_bounce_loop(self):
        page = FakeGooglePage(start="email")
        out = _complete_google_auth(page, page.email, "not-a-real-password", timeout_sec=5)
        self.assertEqual(out, "ok")
        self.assertEqual(page.email_bounces, 0)
        self.assertGreaterEqual(len(page.password_fills), 1)
        self.assertLessEqual(len(page.email_fills), 2)
        self.assertEqual(page.step, "done")

    def test_chooser_then_password(self):
        page = FakeGooglePage(start="chooser")
        out = _complete_google_auth(page, page.email, "not-a-real-password", timeout_sec=5)
        self.assertEqual(out, "ok")
        self.assertEqual(page.email_bounces, 0)
        self.assertGreaterEqual(page.account_picks, 1)
        self.assertGreaterEqual(len(page.password_fills), 1)

    def test_no_endless_next_on_email(self):
        page = FakeGooglePage(start="email")

        def stuck_next(name: str) -> None:
            # Next does nothing — stay on email
            return

        page.handle_click = stuck_next  # type: ignore[method-assign]
        out = _complete_google_auth(page, page.email, "not-a-real-password", timeout_sec=3)
        self.assertIn(out, ("sso_blocked", "password_failed", "challenge"))
        next_clicks = sum(1 for c in page.clicks if str(c).lower() in ("next", "continue"))
        self.assertLessEqual(next_clicks, 3)


if __name__ == "__main__":
    unittest.main()
