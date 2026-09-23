"""Smoke-test hunt routing — masks secrets in output."""

from __future__ import annotations

import json
import re
import urllib.request

BASE = "http://127.0.0.1:8765"
_SECRET = re.compile(
    r"(?:gsk_|sk-ant-|sk-or-|sk_|sk-|AIza|nvapi-|hf_)[A-Za-z0-9_-]{8,}"
)


def post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode())


def mask(text: str) -> str:
    return _SECRET.sub(lambda m: m.group(0)[:8] + "...MASKED...", text)


def summarize(label: str, resp: dict) -> None:
    text = resp.get("response") or resp.get("reply") or str(resp)
    saved = ("Saved to .env" in text) or ("Saved your" in text)
    chat_hint = "save" in text.lower() and ".env" in text.lower() and not saved
    short = mask(text)[:240].replace("\n", " | ")
    print(f"{label}: handled={resp.get('handled')} saved_env={saved} chat_hint={chat_hint}")
    print(f"  -> {short}")


def main() -> None:
    summarize("GET groq /hunt", post("/api/hunt", {"message": "get me groq api key"}))
    summarize("SAVE groq /hunt", post("/api/hunt", {"message": "save groq api to .env"}))
    summarize("GET groq /fast", post("/api/fast", {"message": "get me groq api key"}))
    summarize("time /fast", post("/api/fast", {"message": "what time is it"}))


if __name__ == "__main__":
    main()
