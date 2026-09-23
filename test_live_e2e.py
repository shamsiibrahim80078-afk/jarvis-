#!/usr/bin/env python3
"""Live end-to-end Jarvis tests — hits the real server so you can watch Chrome/HUD."""

from __future__ import annotations

import json
import time
import urllib.request
import webbrowser
from pathlib import Path

API = "http://127.0.0.1:8765"
ROOT = Path(__file__).resolve().parent
RESULTS: list[tuple[str, bool, str]] = []


def get(path: str) -> dict:
    with urllib.request.urlopen(f"{API}{path}", timeout=20) as r:
        return json.loads(r.read().decode())


def post(path: str, body: dict, timeout: int = 30) -> dict:
    req = urllib.request.Request(
        f"{API}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f" — {detail[:140]}" if detail else ""))


def test_health() -> None:
    print("\n=== 1. SERVER HEALTH ===")
    try:
        h = get("/api/health")
        check("health", h.get("status") == "online", str(h))
        s = get("/api/status")
        check("status", "cpu" in s, f"cpu={s.get('cpu')} ram={s.get('memory')}")
    except Exception as exc:
        check("health", False, str(exc))
        raise SystemExit("Server not running — start start-server.bat first")


def test_fast(command: str, expect_substr: str | None = None) -> str:
    data = post("/api/fast", {"message": command})
    resp = data.get("response") or ""
    handled = bool(data.get("handled"))
    ok = handled and (expect_substr is None or expect_substr.lower() in resp.lower())
    check(f"fast: {command}", ok, resp[:160])
    return resp


def test_hunt(command: str, max_sec: int = 180) -> str:
    try:
        post("/api/hunt-reset", {})
    except Exception:
        pass

    print(f"\n  >>> LIVE HUNT: {command}")
    print("  Watch Chrome — email must go in EMAIL box, password in PASSWORD box.")
    data = post("/api/hunt", {"message": command})
    immediate = data.get("response") or ""
    print(f"  Immediate: {immediate[:160]}")

    if "already have" in immediate.lower():
        check(f"hunt: {command}", True, immediate[:160])
        return immediate

    for i in range(max_sec // 5):
        time.sleep(5)
        st = get("/api/hunt-status")
        status = st.get("status", "?")
        resp = st.get("response") or ""
        print(f"    [{i * 5:3d}s] {status}: {resp[:100]}")
        if status in ("done", "error"):
            ok = status == "done" and (
                "Got your" in resp
                or "already have" in resp.lower()
                or "Chrome is still open" in resp
                or "Saved to .env" in resp
            )
            # Playwright crash = fail
            if "PlaywrightContextManager" in resp or "No module named" in resp:
                ok = False
            if "password" in resp.lower() and "email" in resp.lower() and "Error" in resp:
                ok = False
            check(f"hunt: {command}", ok, resp[:200])
            return resp

    check(f"hunt: {command}", False, "TIMEOUT")
    return "TIMEOUT"


def main() -> int:
    print("=" * 64)
    print("JARVIS LIVE END-TO-END TEST")
    print("Open http://127.0.0.1:8765 and watch — Chrome will open for hunts")
    print("=" * 64)

    test_health()

    # Open HUD so Ibrahim can see
    try:
        webbrowser.open(API)
        print("\n  Opened Jarvis HUD in your browser.")
    except Exception:
        pass

    print("\n=== 2. INSTANT COMMANDS (no AI brain) ===")
    test_fast("hey jarvis", "sir")
    test_fast("what time is it")
    test_fast("open youtube and search for lofi music", "youtube")
    test_fast("open groq", "chrome")
    test_fast("get me the 11 lab api key")  # must route to hunt, not brain
    # Reset after accidental hunt start from above
    try:
        post("/api/hunt-reset", {})
        time.sleep(1)
    except Exception:
        pass

    print("\n=== 3. API HUNT — GROQ (refresh so Chrome opens) ===")
    print("  THIS is the email/password fix test — watch the Groq login form.")
    test_hunt("refresh groq api key", max_sec=120)

    print("\n=== 4. API HUNT — ELEVENLABS ===")
    test_hunt("get me eleven labs api key", max_sec=180)

    print("\n=== 5. ROUTING — must NOT hit Groq 429 ===")
    r = post("/api/command", {"message": "get me the 11 lab api key", "speak": False})
    resp = r.get("response") or ""
    source = r.get("source") or ""
    bad = "429" in resp or "rate_limit" in resp or "neural network" in resp.lower()
    check("no-429 on api command", not bad and source in ("api_hunt", "fast", "plugin"), f"source={source} | {resp[:120]}")

    print("\n" + "=" * 64)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"RESULTS: {passed} passed, {failed} failed")
    for name, ok, detail in RESULTS:
        if not ok:
            print(f"  FAIL -> {name}: {detail[:180]}")
    print("=" * 64)

    log = ROOT / "data" / "hunt_worker.log"
    if log.exists():
        print("\nHunt worker log:")
        print(log.read_text(encoding="utf-8")[-800:])

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
