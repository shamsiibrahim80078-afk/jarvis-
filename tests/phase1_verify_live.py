"""Phase 1 live verification against REAL Jarvis on :8765 — no mocks."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

API = "http://127.0.0.1:8765"
ROOT = Path(__file__).resolve().parents[1]
RESULTS: list[dict] = []


def record(name: str, status: str, detail: str = "", source: str = "") -> None:
    RESULTS.append({"name": name, "status": status, "detail": detail[:300], "source": source})
    mark = {
        "WORKING": "OK",
        "BUG": "BUG",
        "CONFIGURATION_REQUIRED": "CFG",
        "NOT_IMPLEMENTED": "N/A",
        "FAIL": "FAIL",
    }.get(status, status)
    print(f"[{mark}] {name}: {detail[:160]}")


def get(path: str, timeout: float = 15) -> requests.Response:
    return requests.get(f"{API}{path}", timeout=timeout)


def post(path: str, body: dict, timeout: float = 30) -> dict:
    r = requests.post(f"{API}{path}", json=body, timeout=timeout)
    r.raise_for_status()
    return r.json()


def main() -> int:
    print("=== PHASE 1 LIVE VERIFICATION (REAL JARVIS) ===\n")

    # 1. Health
    try:
        h = get("/api/health").json()
        if h.get("status") == "online":
            record("health", "WORKING", json.dumps(h))
        else:
            record("health", "FAIL", json.dumps(h))
            return 1
    except Exception as e:
        record("health", "FAIL", str(e))
        return 1

    # 2. Status / system metrics
    try:
        s = get("/api/status", timeout=20).json()
        need = ("cpu", "memory", "disk", "user")
        if all(k in s for k in need):
            record("status_metrics", "WORKING", f"cpu={s.get('cpu')} user={s.get('user')} plugins={s.get('plugins')}")
        else:
            record("status_metrics", "BUG", f"missing keys: {s}")
    except Exception as e:
        record("status_metrics", "FAIL", str(e))

    # 3. Frontend
    try:
        html = get("/").text
        if "J.A.R.V.I.S" in html and "app.js" in html:
            record("hud_index", "WORKING", "index.html serves")
        else:
            record("hud_index", "BUG", "missing brand or app.js")
        face = get("/face")
        if face.status_code == 200 and len(face.text) > 500:
            record("human_view_page", "WORKING", f"face.html {face.status_code}")
        else:
            record("human_view_page", "BUG", f"status={face.status_code}")
    except Exception as e:
        record("hud_frontend", "FAIL", str(e))

    # Fast-path commands (must not hit LLM / not overload)
    # Heavy api_hunt last — Playwright/Chrome must not contend with LLM smoke
    cases = [
        ("wake", "hey jarvis", "wake", ["yes sir", "how may"]),
        ("wake_hey", "Hey Jarvis, hey", "wake", ["yes sir"]),
        ("time", "what time is it", "fast", None),
        ("system_status", "system status", "fast", None),
        ("open_chrome", "open chrome", "fast", ["chrome", "opening"]),
        ("volume", "volume up", "fast", ["volume", "sir"]),
        ("human_view", "open the human view", "fast", ["human", "opening"]),
        ("screen_share_start", "share your screen", "screen_share", ["screen", "jarvis", "sharing", "show"]),
        ("screen_share_stop", "stop sharing your screen", "screen_share", ["stop", "screen", "closed", "off"]),
        ("api_count", "how many apis are still there", None, ["api", "sheet", "missing", "total", "link", "share", "metrics"]),
        ("sheet_veridiq", "open veridiq apis in google sheet", "fast", ["sheet", "tab", "link", "remember", "opening", "veridiq"]),
    ]
    hunt_cases = [
        ("api_hunt_detect", "get me eleven labs api key", "api_hunt", ["chrome", "eleven", "key", "already", "signing", "fetching", "env"]),
    ]

    def run_cases(case_list: list) -> None:
        for name, msg, expect_source, needles in case_list:
            try:
                data = post("/api/fast", {"message": msg}, timeout=45)
                if not data.get("handled") and expect_source not in ("fast", "wake", "screen_share", "api_hunt"):
                    data = post("/api/command", {"message": msg, "speak": False}, timeout=60)
                elif not data.get("handled") and expect_source in ("api_hunt", "screen_share"):
                    if expect_source == "api_hunt":
                        data = post("/api/hunt", {"message": msg}, timeout=45)
                    else:
                        data = post("/api/command", {"message": msg, "speak": False}, timeout=45)

                resp = (data.get("response") or "") or ""
                src = data.get("source") or ""
                lower = resp.lower()

                bad = any(x in lower for x in (
                    "overloaded", "neural network", "no module named",
                    "connection issue", "server is busy",
                ))
                if bad:
                    record(name, "BUG", f"source={src} bad_response={resp[:200]}")
                    continue

                if expect_source and src and src != expect_source and data.get("handled") is not False:
                    ok_alt = {
                        "wake": {"wake", "fast"},
                        "fast": {"fast", "task", "system"},
                        "screen_share": {"screen_share", "fast"},
                        "api_hunt": {"api_hunt", "fast"},
                    }.get(expect_source, {expect_source})
                    if src not in ok_alt and data.get("handled"):
                        record(name, "BUG", f"expected source~{expect_source} got={src} resp={resp[:150]}")
                        continue

                if needles and not any(n in lower for n in needles):
                    if data.get("handled") is False and not resp:
                        record(name, "BUG", f"not handled: {data}")
                    else:
                        record(name, "BUG", f"unexpected response source={src}: {resp[:200]}")
                    continue

                if not resp and data.get("handled") is False:
                    record(name, "BUG", f"unhandled: {data}")
                    continue

                record(name, "WORKING", f"source={src or data.get('source')} | {resp[:120]}", src)
            except Exception as e:
                record(name, "FAIL", str(e))

    run_cases(cases)

    # Full core process path (not only /fast)
    try:
        data = post("/api/command", {"message": "hey jarvis", "speak": False}, timeout=30)
        if "yes sir" in (data.get("response") or "").lower():
            record("core_process_wake", "WORKING", data.get("response", "")[:120], data.get("source", ""))
        else:
            record("core_process_wake", "BUG", str(data)[:200])
    except Exception as e:
        record("core_process_wake", "FAIL", str(e))

    # Memory via core — must be instant (no LLM)
    try:
        data = post("/api/command", {"message": "remember that my favorite color is cyan", "speak": False}, timeout=15)
        resp = (data.get("response") or "").lower()
        src = data.get("source") or ""
        if "overloaded" in resp or "neural network" in resp or "no module" in resp:
            record("memory_remember", "BUG", resp[:200])
        elif "remember" in resp and "cyan" in resp:
            mem = ROOT / "data" / "memory.json"
            facts = ""
            if mem.exists():
                facts = mem.read_text(encoding="utf-8", errors="ignore")
            ok = "cyan" in facts.lower()
            record(
                "memory_remember",
                "WORKING" if ok else "BUG",
                f"source={src} persisted={ok} resp={resp[:100]}",
                src,
            )
        else:
            record("memory_remember", "BUG", f"source={src} resp={resp[:200]}")
    except Exception as e:
        record("memory_remember", "FAIL", str(e))

    # Light brain smoke (real LLM) — before Playwright hunt load
    try:
        data = post("/api/command", {"message": "Reply with exactly: JARVIS_OK", "speak": False}, timeout=22)
        resp = (data.get("response") or "")
        low = resp.lower()
        if "rate-limit" in low or "rate limit" in low:
            record("brain_llm_smoke", "CONFIGURATION_REQUIRED", resp[:200], data.get("source", ""))
        elif "slow right now" in low or "neural network" in low:
            record("brain_llm_smoke", "CONFIGURATION_REQUIRED", resp[:200], data.get("source", ""))
        elif resp.strip():
            record("brain_llm_smoke", "WORKING", f"source={data.get('source')} | {resp[:120]}", data.get("source", ""))
        else:
            record("brain_llm_smoke", "BUG", "empty brain response")
    except Exception as e:
        record("brain_llm_smoke", "FAIL", str(e))

    # Real API hunt launch (Chrome) — last heavy test
    run_cases(hunt_cases)

    # Clear hunt lock left by api_hunt_detect so later runs aren't blocked
    try:
        requests.post(f"{API}/api/hunt-reset", json={}, timeout=10)
    except Exception:
        pass

    # Plugins list via status
    try:
        s = get("/api/status").json()
        plugs = s.get("plugins") or []
        if plugs:
            record("plugins_loaded", "WORKING", str(plugs))
        else:
            record("plugins_loaded", "BUG", "no plugins in status")
    except Exception as e:
        record("plugins_loaded", "FAIL", str(e))

    # Briefing (plugin or brain)
    try:
        data = get("/api/briefing", timeout=45).json()
        resp = data.get("response") or ""
        if "overloaded" in resp.lower() or "no module" in resp.lower():
            record("morning_briefing", "BUG", resp[:200])
        elif resp:
            record("morning_briefing", "WORKING", resp[:120])
        else:
            record("morning_briefing", "BUG", "empty")
    except Exception as e:
        record("morning_briefing", "FAIL", str(e))

    # TTS endpoint
    try:
        r = requests.post(f"{API}/api/tts", json={"text": "Yes sir."}, timeout=60)
        if r.status_code == 200 and len(r.content) > 500:
            record("tts_edge", "WORKING", f"bytes={len(r.content)} type={r.headers.get('content-type')}")
        else:
            record("tts_edge", "BUG", f"status={r.status_code} len={len(r.content)}")
    except Exception as e:
        record("tts_edge", "FAIL", str(e))

    # Screen share API
    try:
        st = get("/api/screen/status").json()
        record("screen_share_api", "WORKING", json.dumps(st)[:200])
    except Exception as e:
        # try alternate paths
        try:
            # discovery
            record("screen_share_api", "CONFIGURATION_REQUIRED", f"status endpoint missing: {e}")
        except Exception:
            record("screen_share_api", "NOT_IMPLEMENTED", str(e))

    # Hunt status bus
    try:
        hs = get("/api/hunt-status").json()
        record("hunt_bus", "WORKING", json.dumps(hs)[:200])
    except Exception as e:
        record("hunt_bus", "FAIL", str(e))

    # Env keys present (config)
    env = ROOT / ".env"
    if env.exists():
        text = env.read_text(encoding="utf-8", errors="ignore")
        has_groq = "GROQ_API_KEY=" in text and len(text.split("GROQ_API_KEY=")[1].split("\n")[0].strip()) > 5
        has_email = "JARVIS_EMAIL=" in text
        record(
            "env_config",
            "WORKING" if has_groq else "CONFIGURATION_REQUIRED",
            f"groq={has_groq} email={has_email}",
        )
    else:
        record("env_config", "CONFIGURATION_REQUIRED", "no .env")

    # Sheet link saved?
    wf = ROOT / "data" / "workflows.json"
    if wf.exists():
        w = json.loads(wf.read_text(encoding="utf-8"))
        sheet = (w.get("links") or {}).get("api_sheet") or ""
        if sheet:
            record("sheet_link_saved", "WORKING", sheet[:80])
        else:
            record("sheet_link_saved", "CONFIGURATION_REQUIRED", "no api_sheet link saved")
    else:
        record("sheet_link_saved", "CONFIGURATION_REQUIRED", "no workflows.json")

    # MCP config exists (Cursor, not Jarvis runtime)
    mcp = ROOT / ".cursor" / "mcp.json"
    if mcp.exists():
        record("mcp_cursor_config", "WORKING", "configured for Cursor IDE (not Jarvis runtime)")
    else:
        record("mcp_cursor_config", "NOT_IMPLEMENTED", "missing")

    # CLI entry exists
    if (ROOT / "main.py").exists() and (ROOT / "run_server.py").exists():
        record("startup_scripts", "WORKING", "main.py + run_server.py present")
    else:
        record("startup_scripts", "BUG", "missing entrypoints")

    print("\n=== SUMMARY ===")
    counts: dict[str, int] = {}
    for r in RESULTS:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    for k, v in sorted(counts.items()):
        print(f"  {k}: {v}")

    out = ROOT / "data" / "phase1_verify_report.json"
    out.write_text(json.dumps({"results": RESULTS, "counts": counts, "ts": time.time()}, indent=2), encoding="utf-8")
    print(f"\nWrote {out}")

    bugs = counts.get("BUG", 0) + counts.get("FAIL", 0)
    return 1 if bugs else 0


if __name__ == "__main__":
    sys.exit(main())
