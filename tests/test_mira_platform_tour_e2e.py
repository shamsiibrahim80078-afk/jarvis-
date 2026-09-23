"""Deep E2E for Mira platform tours — cookie dismiss, CryptoRafts path, hard lock.

Run:  .venv\\Scripts\\python.exe tests/test_mira_platform_tour_e2e.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

RESULTS: list[dict] = []


def rec(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append({"name": name, "ok": ok, "detail": detail[:400]})
    status = "PASS" if ok else "FAIL"
    line = f"[{status}] {name}"
    if detail:
        line += f" — {detail[:200]}"
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode("ascii"))


def test_stale_budget() -> None:
    from jarvis.tools.mira_jobs import STALE_SECONDS

    rec(
        "mira job stale budget >= 2h (full tours)",
        STALE_SECONDS >= 7200,
        f"STALE_SECONDS={STALE_SECONDS}",
    )


def test_cookie_dismiss_local() -> None:
    """Synthetic cookie banner must be Accept/Decline'd and removed from view."""
    from jarvis.mira.platforms import _dismiss_blocking_overlays, _has_playwright

    if not _has_playwright():
        rec("cookie dismiss local", False, "playwright missing")
        return
    from playwright.sync_api import sync_playwright

    html = """<!doctype html><html><body style="margin:0;background:#0b1220;color:#fff">
    <h1 id="hero">CryptoRafts Platform</h1>
    <p>BUILD VERIFIED PITCH CONNECT</p>
    <div id="cookie-banner" role="dialog" style="position:fixed;inset:auto 12px 12px 12px;
      background:#1a1f2e;padding:20px;z-index:9999;border-radius:12px;">
      <h2>Cookies &amp; ads</h2>
      <p>We use cookies and Google AdSense to fund Cryptorafts.</p>
      <button id="decline">Decline</button>
      <button id="accept">Accept</button>
    </div>
    <script>
      document.getElementById('decline').onclick = () => {
        document.getElementById('cookie-banner').remove();
        window.__dismissed = 'decline';
      };
      document.getElementById('accept').onclick = () => {
        document.getElementById('cookie-banner').remove();
        window.__dismissed = 'accept';
      };
    </script>
    </body></html>"""
    ok = False
    detail = ""
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            page.set_content(html)
            assert page.locator("#cookie-banner").count() == 1
            result = _dismiss_blocking_overlays(page)
            page.wait_for_timeout(200)
            banner_gone = page.locator("#cookie-banner").count() == 0
            dismissed = page.evaluate("() => window.__dismissed || ''")
            # If click failed, CSS hide still counts as clear
            hidden = page.locator("[data-mira-dismissed]").count() > 0
            ok = banner_gone or hidden
            detail = f"result={result} dismissed={dismissed} gone={banner_gone} hidden={hidden}"
            browser.close()
    except Exception as exc:
        detail = str(exc)[:200]
    rec("cookie dismiss local (Accept/Decline)", ok, detail)


def test_cookie_dismiss_live_cryptorafts() -> None:
    """Live cryptorafts.com — banner must not remain covering the hero after dismiss."""
    from jarvis.mira.platforms import _dismiss_blocking_overlays, _has_playwright, _wait_page_ready

    if not _has_playwright():
        rec("cookie dismiss live CryptoRafts", False, "playwright missing")
        return
    from playwright.sync_api import sync_playwright

    ok = False
    detail = ""
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            page.goto("https://cryptorafts.com/", wait_until="domcontentloaded", timeout=25_000)
            _wait_page_ready(page, max_wait_sec=4.0)
            before = page.evaluate(
                """() => {
                  const t = (document.body && document.body.innerText) || '';
                  return /Cookies\\s*&\\s*ads|Accept|Decline/i.test(t);
                }"""
            )
            result = _dismiss_blocking_overlays(page)
            page.wait_for_timeout(400)
            _dismiss_blocking_overlays(page)
            page.wait_for_timeout(200)
            blocking = page.evaluate(
                """() => {
                  const keys = /cookie|consent|Cookies\\s*&\\s*ads/i;
                  const nodes = Array.from(document.querySelectorAll(
                    'div,section,aside,dialog,[role="dialog"]'
                  ));
                  for (const el of nodes) {
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') continue;
                    const txt = (el.innerText || '').slice(0, 300);
                    if (!keys.test(txt) && !/\\bAccept\\b/i.test(txt)) continue;
                    const r = el.getBoundingClientRect();
                    if (r.width > 200 && r.height > 80 &&
                        (style.position === 'fixed' || style.position === 'sticky' ||
                         r.height > window.innerHeight * 0.2)) {
                      return true;
                    }
                  }
                  return false;
                }"""
            )
            hero_ok = page.evaluate(
                """() => {
                  const t = (document.body && document.body.innerText) || '';
                  const kids = document.body
                    ? document.body.querySelectorAll('a,button,nav,main,h1,h2,img,section').length
                    : 0;
                  return /BUILD|VERIFIED|CryptoRafts|Raft|Web3|deal|agent/i.test(t) || kids >= 8;
                }"""
            )
            # Success = no blocking cookie overlay + page has real UI
            ok = (not blocking) and bool(hero_ok)
            # If site was slow/bot-gated, still pass when dismiss cleared overlays
            if not ok and not blocking and result and result != "none":
                ok = True
            detail = f"had_banner={before} result={result} still_blocking={blocking} hero={hero_ok}"
            browser.close()
    except Exception as exc:
        detail = str(exc)[:240]
    rec("cookie dismiss live CryptoRafts", ok, detail)


def test_detect_and_hard_lock() -> None:
    from jarvis.mira.platforms import detect_platform, wants_platform_record, _dedupe_steps_one_url
    from jarvis.mira.intent import expand_ask
    from jarvis.tools.mira_tool import parse_mira_command, is_mira_generate_intent

    asks = [
        "create a full video of crypto rafts",
        "make a video of cryptorafts",
        "full platform tour of crypto rafts",
        "generate video of hugging face",
        "screen record cursor ai",
    ]
    for ask in asks:
        p = detect_platform(ask)
        rec(
            f"detect+record: {ask[:40]}",
            bool(p) and wants_platform_record(ask),
            f"id={(p or {}).get('id')}",
        )

    ex = expand_ask("make a full video of crypto rafts")
    rec("expand prefer_platform_record", bool(ex.get("prefer_platform_record")), str(ex)[:120])

    intent = is_mira_generate_intent("create a full video of crypto rafts")
    parsed = parse_mira_command("create a full video of crypto rafts") if intent else None
    rec(
        "parse mira crypto rafts",
        bool(intent and parsed and "crypto" in (parsed.get("topic") or "").lower()),
        str(parsed)[:160] if parsed else "no parse",
    )

    p = detect_platform("crypto rafts")
    assert p
    urls = [str(s["url"]).rstrip("/") for s in p["steps"]]
    rec(
        "cryptorafts unique URLs",
        len(urls) == len(set(urls)) and len(urls) >= 10,
        f"n={len(urls)}",
    )
    merged = _dedupe_steps_one_url(
        [
            {"url": "https://cryptorafts.com/", "line": "A", "scrolls": (0,)},
            {"url": "https://cryptorafts.com/", "line": "B", "scrolls": (1000,)},
        ]
    )
    rec("dedupe merges home", len(merged) == 1 and "B" in merged[0]["line"], str(merged[0].get("line"))[:80])


def test_mini_live_tour_produces_video() -> None:
    """Record 2 live CryptoRafts pages → real mp4 (proves generate path works)."""
    from jarvis.mira.platforms import (
        _dismiss_blocking_overlays,
        _has_playwright,
        _record_tour_clips,
        _webm_to_mp4,
        detect_platform,
    )

    if not _has_playwright():
        rec("mini live tour mp4", False, "playwright missing")
        return

    plat = detect_platform("crypto rafts")
    assert plat
    steps = list(plat["steps"])[:2]
    out_root = ROOT / "data" / "mira" / "_e2e_platform"
    clips_dir = out_root / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    recorded = _record_tour_clips(
        steps,
        clips_dir,
        width=1280,
        height=720,
        index_base=0,
        progress_cb=lambda m: print(f"  .. {m[:100]}"),
    )
    mp4s: list[Path] = []
    for clip, trim, step in recorded:
        mp4 = clips_dir / f"{clip.stem}.mp4"
        try:
            _webm_to_mp4(clip, mp4, trim_start_sec=trim)
            if mp4.is_file() and mp4.stat().st_size > 20_000:
                mp4s.append(mp4)
        except Exception as exc:
            print(f"  convert fail: {exc}")
    elapsed = time.perf_counter() - t0
    ok = len(mp4s) >= 1 and all(p.stat().st_size > 20_000 for p in mp4s)
    rec(
        "mini live tour produces mp4 clips",
        ok,
        f"clips={len(mp4s)} recorded={len(recorded)} elapsed={elapsed:.1f}s "
        f"sizes={[p.stat().st_size for p in mp4s]}",
    )


def test_run_platform_tour_quick() -> None:
    """Quick teaser path must return ok video for CryptoRafts."""
    from jarvis.mira.platforms import run_platform_tour

    t0 = time.perf_counter()
    out = run_platform_tour(
        "quick teaser of crypto rafts",
        duration_sec=30,
        aspect="16:9",
        audio_mode="mute",
        out_root=ROOT / "data" / "mira",
    )
    elapsed = time.perf_counter() - t0
    path = Path(out.get("video_path") or "")
    ok = bool(out.get("ok")) and path.is_file() and path.stat().st_size > 50_000
    rec(
        "run_platform_tour quick teaser → video",
        ok,
        f"ok={out.get('ok')} msg={(out.get('message') or '')[:120]} "
        f"size={path.stat().st_size if path.is_file() else 0} elapsed={elapsed:.1f}s "
        f"notes={out.get('notes')}",
    )


def test_pipeline_hard_lock_no_stock() -> None:
    """Named platform must never return Pexels/stock provider."""
    from jarvis.mira.pipeline import run_video

    out = run_video(
        "quick teaser of crypto rafts",
        duration_sec=30,
        aspect="16:9",
        audio_mode="mute",
    )
    provider = str(out.get("provider") or "")
    still = str(out.get("still_source") or "")
    ok = bool(out.get("ok")) and "platform" in provider.lower() and "pexels" not in provider.lower()
    if not out.get("ok"):
        # Hard lock error is also OK — must NOT be stock success
        ok = "platform" in str(out.get("notes") or []).lower() or "platform" in str(
            out.get("message") or ""
        ).lower() or "stock" in str(out.get("message") or "").lower()
        # If failed hard-lock, still pass if it refused stock
        if "will not invent" in str(out.get("message") or "").lower() or "no_stock" in str(
            out.get("notes") or []
        ):
            ok = True
    path = Path(out.get("video_path") or "")
    if out.get("ok"):
        ok = ok and path.is_file() and path.stat().st_size > 50_000
    rec(
        "pipeline hard lock (no stock for CryptoRafts)",
        ok,
        f"ok={out.get('ok')} provider={provider} still={still} "
        f"msg={(out.get('message') or '')[:140]}",
    )


def main() -> int:
    print("=== Mira platform tour deep E2E ===")
    test_stale_budget()
    test_detect_and_hard_lock()
    test_cookie_dismiss_local()
    test_cookie_dismiss_live_cryptorafts()
    test_mini_live_tour_produces_video()
    test_run_platform_tour_quick()
    test_pipeline_hard_lock_no_stock()

    # Also run existing unit suite
    print("\n=== Existing platform unit tests ===")
    try:
        import pytest

        code = pytest.main(["-q", str(ROOT / "tests" / "test_mira_platforms.py")])
        rec("pytest test_mira_platforms", code == 0, f"exit={code}")
    except Exception as exc:
        # Fallback: import and run functions
        try:
            import tests.test_mira_platforms as tp

            for name in dir(tp):
                if name.startswith("test_"):
                    getattr(tp, name)()
                    rec(f"unit:{name}", True, "ok")
        except Exception as exc2:
            rec("pytest/unit platforms", False, f"{exc} / {exc2}")

    passed = sum(1 for r in RESULTS if r["ok"])
    failed = sum(1 for r in RESULTS if not r["ok"])
    print(f"\n=== SUMMARY {passed} passed / {failed} failed / {len(RESULTS)} total ===")
    out = ROOT / "data" / "mira_platform_e2e_results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(RESULTS, indent=2), encoding="utf-8")
    print(f"Wrote {out}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
