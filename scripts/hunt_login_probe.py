"""Probe login pages across providers — warm Google + detect sign-in UI (no key steal).

Run: python scripts/hunt_login_probe.py
Optional: python scripts/hunt_login_probe.py elevenlabs groq openrouter
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")


def main() -> int:
    from jarvis.tools.credentials import get_user_email, get_user_password
    from jarvis.tools.api_hunter import (
        CHROME_PROFILE,
        PROVIDERS,
        _ensure_google_session,
        _goto_login,
        _email_visible,
        _password_visible,
        _on_google_accounts,
        _release_browser,
        _safe_wait,
    )
    from playwright.sync_api import sync_playwright

    email = get_user_email() or ""
    password = get_user_password() or ""
    if not email or not password:
        print("FAIL: JARVIS_EMAIL / JARVIS_PASSWORD missing in .env")
        return 1

    want = [a.lower() for a in sys.argv[1:]] or [
        "elevenlabs",
        "groq",
        "openrouter",
        "fish",
        "huggingface",
    ]
    providers = [p for p in want if p in PROVIDERS]
    if not providers:
        print("No known providers in args")
        return 1

    CHROME_PROFILE.mkdir(parents=True, exist_ok=True)
    _release_browser()
    print(f"Probing {providers} as {email}")

    with sync_playwright() as pw:
        try:
            ctx = pw.chromium.launch_persistent_context(
                str(CHROME_PROFILE),
                channel="chrome",
                headless=False,
                viewport={"width": 1280, "height": 900},
            )
        except Exception:
            ctx = pw.chromium.launch_persistent_context(
                str(CHROME_PROFILE),
                headless=False,
                viewport={"width": 1280, "height": 900},
            )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        warm = _ensure_google_session(page, email, password)
        print(f"GOOGLE_WARM={warm}")

        results: list[str] = []
        for pid in providers:
            cfg = PROVIDERS[pid]
            print(f"\n=== {pid} ===")
            _goto_login(page, cfg["login"])
            _safe_wait(page, 2500)
            url = page.url
            has_email = _email_visible(page)
            has_pwd = _password_visible(page)
            on_google = _on_google_accounts(page)
            # Detect Google button
            google_btn = False
            try:
                google_btn = page.get_by_role(
                    "button", name=__import__("re").compile(r"google", __import__("re").I)
                ).first.is_visible(timeout=1500)
            except Exception:
                try:
                    google_btn = page.get_by_text(
                        __import__("re").compile(r"continue with google|sign in with google", __import__("re").I)
                    ).first.is_visible(timeout=1000)
                except Exception:
                    pass
            line = (
                f"{pid}: url_ok={bool(url)} google_btn={google_btn} "
                f"email_field={has_email} password_field={has_pwd} on_google={on_google}"
            )
            print(line)
            results.append(line)
            time.sleep(1)

        print("\nSUMMARY")
        for r in results:
            print(" ", r)
        print(f" google_warm={warm}")
        # Leave browser open briefly so you can see; then close
        time.sleep(2)
        ctx.close()
    return 0 if warm == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
