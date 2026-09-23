"""Quick multi-turn E2E against live Jarvis — no mocks."""
from __future__ import annotations

import time

import requests

API = "http://127.0.0.1:8765"


def main() -> None:
    flows = [
        ("wake", "hey jarvis"),
        ("time", "what time is it"),
        ("mem", "remember that phase1 verification passed"),
        ("brain", "In one short sentence, confirm you are Jarvis."),
        ("count", "how many apis are still there"),
    ]
    for name, msg in flows:
        t0 = time.time()
        r = requests.post(
            f"{API}/api/command",
            json={"message": msg, "speak": False},
            timeout=30,
        )
        j = r.json()
        print(
            f"{name}: {round(time.time() - t0, 2)}s "
            f"src={j.get('source')} | {(j.get('response') or '')[:160]}"
        )

    r = requests.post(f"{API}/api/tts", json={"text": "Systems nominal, sir."}, timeout=30)
    print("tts", r.status_code, len(r.content))
    print("health", requests.get(f"{API}/api/health", timeout=10).json())


if __name__ == "__main__":
    main()
