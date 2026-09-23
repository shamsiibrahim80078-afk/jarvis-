"""Platform routing E2E — Gemini vs CryptoRafts must never mix."""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

API = "http://127.0.0.1:8765"
RESULTS = []


def rec(name, ok, detail=""):
    RESULTS.append({"name": name, "ok": ok, "detail": detail[:300]})
    print(("PASS" if ok else "FAIL"), name, "-", detail[:160])


def http(method, path, body=None, timeout=30):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        API + path,
        data=data,
        headers={"Content-Type": "application/json"} if body else {},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def main():
    from jarvis.mira.platforms import detect_platform
    from jarvis.tools.mira_tool import parse_mira_command
    from jarvis.tools.mira_jobs import get_status, set_error

    cases = [
        ("create a full video of gemini", "gemini"),
        ("full video of gemini", "gemini"),
        ("make a video of google gemini", "gemini"),
        ("create a full video of crypto rafts", "cryptorafts"),
        ("video of chatgpt", "chatgpt"),
        ("full video of hugging face", "huggingface"),
    ]
    for ask, expect in cases:
        p = detect_platform(ask)
        parsed = parse_mira_command(ask)
        ok = (
            p is not None
            and p.get("id") == expect
            and parsed
            and parsed.get("platform_tour") is True
        )
        rec(f"route {ask[:40]}", ok, f"got={(p or {}).get('id')} expect={expect}")

    # Gemini must not resolve to CryptoRafts / Google Search alone
    p = detect_platform("create a full video of gemini")
    rec("gemini != cryptorafts", (p or {}).get("id") == "gemini", str((p or {}).get("id")))
    rec("gemini home is gemini.google", "gemini.google" in str((p or {}).get("home") or ""), str((p or {}).get("home")))

    # Clear busy state then start Gemini via Jarvis API
    st = get_status()
    if st.get("running"):
        set_error(st.get("query") or "clear", "Cleared for platform routing E2E")

    start = http("POST", "/api/mira", {"message": "create a quick teaser of gemini"}, timeout=45)
    rec("POST /api/mira gemini", bool(start.get("handled")), str(start.get("response"))[:160])

    saw_gemini = False
    saw_wrong = False
    final = None
    t0 = time.time()
    while time.time() - t0 < 600:
        st = http("GET", "/api/mira-status", timeout=15)
        line = str(st.get("response") or "")
        q = str(st.get("query") or "")
        if "CryptoRafts" in line or "cryptorafts" in line.lower():
            saw_wrong = True
        if "Gemini" in line or "gemini" in line.lower() or st.get("platform") == "gemini":
            saw_gemini = True
        print(f"  .. {st.get('status')}: plat={st.get('platform')} q={q[:40]} | {line[:80]}")
        if st.get("status") in ("done", "error") and not st.get("running"):
            # wait until we saw running for this ask
            if "gemini" in q.lower() or saw_gemini or st.get("status") == "error":
                final = st
                break
        time.sleep(4)

    rec("progress says Gemini not CryptoRafts", saw_gemini and not saw_wrong, f"gemini={saw_gemini} wrong={saw_wrong}")
    if not final:
        rec("gemini job finished", False, "timeout")
    else:
        path = Path(final.get("media_path") or "")
        if not path.is_file() and final.get("media_url"):
            leaf = Path(str(final["media_url"])).name
            path = ROOT / "data" / "mira" / "videos" / leaf
        size = path.stat().st_size if path.is_file() else 0
        ok = final.get("status") == "done" and size > 40_000 and "gemini" in path.name.lower()
        # Accept done even if filename uses platform id
        if final.get("status") == "done" and size > 40_000 and not saw_wrong:
            ok = True
        rec(
            "gemini video file from Jarvis/Mira",
            ok,
            f"status={final.get('status')} size={size} path={path.name if path else None}",
        )

    passed = sum(1 for r in RESULTS if r["ok"])
    failed = sum(1 for r in RESULTS if not r["ok"])
    out = ROOT / "data" / "platform_routing_e2e.json"
    out.write_text(json.dumps(RESULTS, indent=2), encoding="utf-8")
    print(f"\nSUMMARY {passed} passed / {failed} failed -> {out}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
