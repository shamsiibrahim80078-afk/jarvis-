#!/usr/bin/env python3
"""Live Jarvis API hunt tests."""
import json
import sys
import time
import urllib.request

API = "http://127.0.0.1:8765"


def get(path: str) -> dict:
    with urllib.request.urlopen(f"{API}{path}", timeout=15) as r:
        return json.loads(r.read().decode())


def post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"{API}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def hunt_and_wait(command: str, max_sec: int = 240) -> str:
    try:
        post("/api/hunt-reset", {})
    except Exception:
        pass

    print(f"\n>>> COMMAND: {command}")
    resp = post("/api/hunt", {"message": command})
    print("Immediate:", resp.get("response", ""))

    # Instant answer (existing key) — no background hunt
    immediate = resp.get("response", "")
    if "already have" in immediate.lower():
        return immediate

    steps = max_sec // 5
    for i in range(steps):
        time.sleep(5)
        st = get("/api/hunt-status")
        status = st.get("status", "?")
        text = (st.get("response") or "").replace("\n", " ")[:120]
        print(f"  [{i * 5:3d}s] {status}: {text}")
        if status in ("done", "error"):
            return st.get("response", "")

    return "TIMEOUT"


def main() -> int:
    print("=" * 60)
    print("JARVIS LIVE API TESTS")
    print("=" * 60)

    try:
        print("Server:", get("/api/health"))
    except Exception as exc:
        print("FAIL: server down -", exc)
        return 1

    r1 = hunt_and_wait("get me groq api key", max_sec=15)
    print("\nGROQ RESULT:", r1)
    ok1 = "already have" in r1.lower() or "gsk_" in r1

    try:
        post("/api/hunt-reset", {})
    except Exception:
        pass

    r2 = hunt_and_wait("get me eleven labs api key", max_sec=300)
    print("\nELEVENLABS RESULT:", r2)
    ok2 = any(x in r2 for x in ("Got your", "sk_", "Saved to .env", "Chrome is still open"))

    print("\n" + "=" * 60)
    print("GROQ test:", "PASS" if ok1 else "FAIL")
    print("ELEVENLABS test:", "PASS" if ok2 else "FAIL")
    print("=" * 60)
    return 0 if ok1 else 2


if __name__ == "__main__":
    sys.exit(main())
