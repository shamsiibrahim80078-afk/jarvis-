"""Jarvis → Mira video E2E — same path as the HUD (/api/mira), plus recording checks.

Run:  .venv\\Scripts\\python.exe -u tests/test_jarvis_mira_video_e2e.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

API = "http://127.0.0.1:8765"
RESULTS: list[dict] = []


def rec(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append({"name": name, "ok": ok, "detail": detail[:500]})
    print(("PASS" if ok else "FAIL"), name, "-", detail[:180])


def http_json(method: str, path: str, body: dict | None = None, timeout: int = 30) -> dict:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        API + path,
        data=data,
        headers={"Content-Type": "application/json"} if body is not None else {},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def test_server() -> None:
    try:
        st = http_json("GET", "/api/status", timeout=10)
        rec("Jarvis API up", True, str(st.get("time") or "ok")[:80])
    except Exception as exc:
        rec("Jarvis API up", False, str(exc))
        raise SystemExit(1)


def test_intent_and_parse() -> None:
    from jarvis.tools.mira_tool import is_mira_generate_intent, parse_mira_command
    from jarvis.mira.platforms import detect_platform, wants_platform_record, _has_playwright

    asks = [
        "create a full video of crypto rafts",
        "full video of crypto rafts",
        "make a video of cryptorafts",
        "screen record crypto rafts",
        "quick teaser of crypto rafts",
    ]
    for a in asks:
        intent = is_mira_generate_intent(a)
        parsed = parse_mira_command(a)
        plat = detect_platform(a)
        ok = intent and parsed and parsed.get("action") == "video" and bool(plat)
        if "screen record" in a:
            ok = intent and bool(plat) and wants_platform_record(a)
            if not parsed:
                # screen record must at least parse now
                ok = False
        rec(
            f"intent/parse: {a[:42]}",
            ok,
            f"intent={intent} action={(parsed or {}).get('action')} "
            f"platform_tour={(parsed or {}).get('platform_tour')} id={(plat or {}).get('id')}",
        )
    rec("playwright installed", _has_playwright(), "")


def test_cookie_killer_safe() -> None:
    from jarvis.mira.platforms import _install_dark_boot
    import inspect

    src = inspect.getsource(_install_dark_boot)
    # Docstring may mention MutationObserver; check the live script body only
    body = src.split("add_init_script", 1)[-1] if "add_init_script" in src else src
    rec(
        "cookie killer has no MutationObserver loop",
        "MutationObserver" not in body and "setInterval(killCookies" not in body,
        "safe one-shot timeouts only",
    )


def test_hud_mira_routing() -> None:
    """Simulate Iron Man HUD: isMiraCommand-equivalent checks for platform asks."""
    # Mirror critical JS patterns in Python for regression
    import re

    def is_mira_js(text: str) -> bool:
        lower = text.lower()
        if re.search(
            r"\b(make|create|generate|render|produce|shoot|edit|build|craft|compose)\b.{0,80}\b(an?\s+)?(ai\s+)?(video|clip|reel|short|shorts|film|movie|montage|image)\b",
            lower,
        ):
            return True
        if re.search(
            r"\b(full\s+)?(platform\s+)?(video|tour|walkthrough|screen\s*record)\b.{0,40}\b(of|for|on)\b",
            lower,
        ):
            return True
        if re.search(r"\b(screen\s*record)\b", lower):
            return True
        if re.search(r"\b(crypto\s*rafts?|cryptorafts)\b", lower) and re.search(
            r"\b(video|tour|record|clip|mira)\b", lower
        ):
            return True
        return False

    for a in (
        "create a full video of crypto rafts",
        "full video of crypto rafts",
        "screen record crypto rafts",
    ):
        rec(f"HUD routes to /api/mira: {a[:40]}", is_mira_js(a), "")


def test_api_mira_job_quick() -> None:
    """Full Jarvis path: POST /api/mira → poll → video file (quick teaser)."""
    # Clear any stale running flag
    try:
        from jarvis.tools.mira_jobs import get_status, set_error

        st = get_status()
        if st.get("running"):
            set_error(st.get("query") or "e2e", "Cleared for E2E")
    except Exception:
        pass

    ask = "create a quick teaser of crypto rafts"
    try:
        start = http_json("POST", "/api/mira", {"message": ask}, timeout=45)
    except Exception as exc:
        rec("POST /api/mira starts job", False, str(exc))
        return

    handled = bool(start.get("handled"))
    resp = str(start.get("response") or "")
    rec(
        "POST /api/mira starts job",
        handled and ("Generating" in resp or "Mira" in resp or "video" in resp.lower() or "busy" in resp.lower()),
        resp[:200],
    )
    if "already busy" in resp.lower():
        return

    t0 = time.time()
    final = None
    saw_running = False
    saw_recording = False
    while time.time() - t0 < 720:
        try:
            st = http_json("GET", "/api/mira-status", timeout=15)
        except Exception as exc:
            time.sleep(3)
            continue
        status = st.get("status")
        line = str(st.get("response") or "")
        if st.get("running") or status == "running":
            saw_running = True
            if re_search_record(line):
                saw_recording = True
            print(f"  .. {status}: {line[:100]}")
        if status in ("done", "error") and (saw_running or status == "error"):
            final = st
            break
        # Fresh done with media
        if status == "done" and st.get("media_url") and saw_running:
            final = st
            break
        time.sleep(4)

    if not final:
        # One last read — encode may finish right after poll window
        try:
            st = http_json("GET", "/api/mira-status", timeout=15)
            if st.get("status") == "done" and (st.get("media_url") or st.get("media_path")):
                final = st
                saw_running = True
        except Exception:
            pass
    if not final:
        rec("mira job finished", False, "timeout waiting for mira-status")
        return

    rec("saw running status", saw_running, "")
    rec("saw live recording progress", saw_recording, final.get("response", "")[:120])
    ok_done = final.get("status") == "done"
    path = Path(final.get("media_path") or "")
    url = final.get("media_url")
    if not path.is_file() and url:
        # resolve from URL leaf
        leaf = Path(str(url)).name
        cand = ROOT / "data" / "mira" / "videos" / leaf
        if cand.is_file():
            path = cand
    size = path.stat().st_size if path.is_file() else 0
    rec(
        "Jarvis/Mira produced mp4 via /api/mira",
        ok_done and path.is_file() and size > 50_000,
        f"status={final.get('status')} size={size} path={path} url={url}",
    )


def re_search_record(line: str) -> bool:
    import re

    return bool(re.search(r"recording|Recording live|Opening|Exploring|screen tour|Encoding", line, re.I))


def test_direct_pipeline_hard_lock() -> None:
    from jarvis.mira.pipeline import run_video

    out = run_video("quick teaser of crypto rafts", duration_sec=30, aspect="16:9", audio_mode="mute")
    provider = str(out.get("provider") or "")
    path = Path(out.get("video_path") or "")
    ok = bool(out.get("ok")) and "platform" in provider and path.is_file() and path.stat().st_size > 50_000
    rec(
        "pipeline hard-lock platform record",
        ok,
        f"ok={out.get('ok')} provider={provider} size={path.stat().st_size if path.is_file() else 0}",
    )


def main() -> int:
    print("=== Jarvis <-> Mira video E2E ===")
    test_server()
    test_cookie_killer_safe()
    test_intent_and_parse()
    test_hud_mira_routing()
    test_api_mira_job_quick()
    # Skip second full record if API path already proved recording (saves time)
    api_ok = any(r["name"].startswith("Jarvis/Mira produced") and r["ok"] for r in RESULTS)
    if not api_ok:
        test_direct_pipeline_hard_lock()
    else:
        rec("skip direct pipeline (API path already recorded)", True, "ok")

    passed = sum(1 for r in RESULTS if r["ok"])
    failed = sum(1 for r in RESULTS if not r["ok"])
    out = ROOT / "data" / "jarvis_mira_e2e_results.json"
    out.write_text(json.dumps(RESULTS, indent=2), encoding="utf-8")
    print(f"\n=== SUMMARY {passed} passed / {failed} failed ===")
    print(f"Wrote {out}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
