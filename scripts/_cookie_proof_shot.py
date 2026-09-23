"""Quick cookie-clear screenshot proof (Mira recorder path)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright
from jarvis.mira.platforms import (
    _install_dark_boot,
    _dismiss_blocking_overlays,
    _cookie_banner_visible,
    _wait_page_ready,
)

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1280, "height": 720})
    _install_dark_boot(ctx)
    page = ctx.new_page()
    page.goto("https://cryptorafts.com/", wait_until="domcontentloaded", timeout=20_000)
    _wait_page_ready(page, max_wait_sec=3)
    page.evaluate(
        """() => {
          if (document.documentElement) document.documentElement.style.background = '#0b1220';
          if (document.body) {
            document.body.style.background = '#0b1220';
            document.body.style.opacity = '1';
          }
        }"""
    )
    page.wait_for_timeout(700)
    _dismiss_blocking_overlays(page)
    page.wait_for_timeout(400)
    _dismiss_blocking_overlays(page)
    visible = _cookie_banner_visible(page)
    shot = ROOT / "data" / "mira" / "_cookie_proof.png"
    page.screenshot(path=str(shot), full_page=False)
    print("cookie_banner_visible", visible)
    print("shot", shot.resolve(), "bytes", shot.stat().st_size)
    browser.close()
    raise SystemExit(0 if not visible else 1)
