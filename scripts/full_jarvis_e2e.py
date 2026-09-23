"""Full Jarvis deep E2E — live APIs + pipelines + unit suites. Run: python scripts/full_jarvis_e2e.py"""
from __future__ import annotations

import json
import sys
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BASE = "http://127.0.0.1:8765"
fails: list[str] = []
passes = 0


def ok(name: str, cond: object, detail: str = "") -> None:
    global passes
    if cond:
        passes += 1
        print(f"  PASS  {name}" + (f" — {detail[:120]}" if detail else ""))
    else:
        fails.append(name)
        print(f"  FAIL  {name}" + (f" — {detail[:200]}" if detail else ""))


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def http_json(method: str, path: str, body: dict | None = None, timeout: float = 45.0):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", errors="replace")
        try:
            return r.status, json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return r.status, {"_raw": raw[:300]}


def main() -> int:
    t0 = time.perf_counter()
    print("JARVIS FULL DEEP E2E")
    print(f"BASE={BASE}  ROOT={ROOT}")

    # ── 1. Live HTTP surface ──
    section("1) LIVE HTTP SURFACE")
    for path in (
        "/api/health",
        "/api/status",
        "/api/crew/state",
        "/api/crew/events?since=0",
        "/api/hunt-status",
        "/api/mira-status",
        "/api/mira/uploads",
        "/api/screen/status",
        "/api/briefing",
        "/",
        "/workspace",
    ):
        try:
            status, data = http_json("GET", path, timeout=12)
            ok(f"GET {path}", status == 200, str(status))
        except Exception as exc:
            ok(f"GET {path}", False, str(exc))

    # ── 2. Imports / wiring ──
    section("2) MODULE IMPORTS + WIRING")
    modules = [
        "jarvis.api.server",
        "jarvis.brain",
        "jarvis.agent",
        "jarvis.fast_router",
        "jarvis.crew.dispatch",
        "jarvis.crew.registry",
        "jarvis.crew.bus",
        "jarvis.tools.api_hunter",
        "jarvis.tools.api_intent",
        "jarvis.tools.mira_tool",
        "jarvis.tools.mira_jobs",
        "jarvis.tools.hunt_bus",
        "jarvis.mira.pipeline",
        "jarvis.mira.edit",
        "jarvis.mira.clipping",
        "jarvis.mira.director",
        "jarvis.mira.growth",
        "jarvis.mira.schedule",
        "jarvis.mira.youtube_upload",
        "jarvis.mira.pexels",
        "jarvis.voice",
        "jarvis.memory",
    ]
    for m in modules:
        try:
            __import__(m)
            ok(f"import {m}", True)
        except Exception as exc:
            ok(f"import {m}", False, str(exc))

    # ── 3. Crew routing ──
    section("3) CREW ROUTING")
    from jarvis.crew.registry import pick_agent_for_task, list_agents

    agents = list_agents()
    ok("crew agents registered", len(agents) >= 8, f"n={len(agents)}")
    cases = [
        ("Mira make a short about coffee", "mira"),
        ("make a short about tea", "mira"),
        ("bring coffee and bottles", "waiter"),
        ("get groq api key", "hunter"),
        ("get api from https://console.groq.com/keys", "hunter"),
        ("weather today", "weather"),
        ("check my email", "mail"),
        ("what's on my calendar", "calendar"),
        ("open youtube", "youtube"),
        ("good morning briefing", "briefing"),
        ("hey jarvis", "jarvis"),
    ]
    for text, expect in cases:
        got = pick_agent_for_task(text)
        ok(f"route → {expect}", got == expect, f"got={got} text={text!r}")

    # ── 4. Hunt intent / batch gate ──
    section("4) API HUNT INTENT")
    from jarvis.tools.api_intent import is_api_hunt_intent, wants_env_save
    from jarvis.tools.api_pipeline import is_batch_api_command
    from jarvis.tools.api_hunter import detect_provider, PROVIDERS

    ok("providers loaded", len(PROVIDERS) >= 8, f"n={len(PROVIDERS)}")
    ok("hunt groq phrase", is_api_hunt_intent("get me groq api key"))
    ok("hunt url groq", is_api_hunt_intent("get api from https://console.groq.com/keys"))
    ok("url not batch", not is_batch_api_command("get api from https://console.groq.com/keys"))
    ok("sheet is batch", is_batch_api_command("get all apis from sheet"))
    ok("detect groq", detect_provider("get groq api key") == "groq")
    ok("detect eleven", detect_provider("eleven labs api") == "elevenlabs")
    ok("env save yes", wants_env_save("save groq to .env"))
    ok("env save no", not wants_env_save("get me groq api key"))

    # ── 5. Mira parse / edit / clip ──
    section("5) MIRA PARSE · EDIT · CLIP")
    from jarvis.tools.mira_tool import (
        parse_mira_command,
        is_mira_generate_intent,
        is_youtube_watch_intent,
    )
    from jarvis.mira.edit import parse_edit_command, is_edit_intent, edit_video, latest_video
    from jarvis.mira.clipping import looks_like_clip_command
    from jarvis.mira.model import model_identity, generate
    from jarvis.mira.formats import detect_format, detect_mood

    ident = model_identity()
    ok("mira model id", str(ident.get("model_id", "")).startswith("mira_jarvis"))
    ok("mira help", generate("help").get("ok") is True)

    p = parse_mira_command("make a youtube shorts about cooking pasta funny")
    ok(
        "shorts+funny parse",
        bool(p and p.get("action") == "video" and p.get("format") == "youtube_shorts" and p.get("mood") == "funny"),
        str(p)[:160],
    )
    p2 = parse_mira_command("create an image of a futuristic desk")
    ok("image parse", bool(p2 and p2.get("action") == "image"))
    p3 = parse_mira_command("rate this video 5")
    ok("rate parse", bool(p3 and p3.get("action") == "rate" and p3.get("rating") == "5"))
    ok("yt search not mira gen", is_youtube_watch_intent("search cats on youtube") and not is_mira_generate_intent("search cats on youtube"))
    ok("mira gen intent", is_mira_generate_intent("make a video about cats"))

    # chained command should stay video and not swallow desk into office_day
    p4 = parse_mira_command(
        "make a video about agent office morning 30 seconds create an image of a desk"
    )
    ok("chained action=video", bool(p4 and p4.get("action") == "video"), str(p4)[:160] if p4 else "None")
    topic = (p4 or {}).get("topic") or ""
    ok("chained topic no desk", "desk" not in topic.lower(), repr(topic))

    ed = parse_edit_command("crop last video to shorts")
    ok("edit crop", bool(ed and ed.get("action") == "edit" and ed.get("aspect") == "9:16"))
    rem = parse_edit_command("make it funny")
    ok("remake funny", bool(rem and rem.get("action") == "remake" and rem.get("mood") == "funny"))
    ok("edit mute intent", is_edit_intent("mute the video audio"))
    ok("clip intent", looks_like_clip_command("clip this video into shorts"))
    ok("format shorts", detect_format("youtube shorts about dogs") == "youtube_shorts")
    ok("mood funny", detect_mood("make it funny") == "funny")

    vid = latest_video()
    if vid and vid.is_file():
        out = edit_video(source=str(vid), aspect="9:16", duration_sec=2, mute=True, label="full_e2e")
        ok("ffmpeg edit", bool(out.get("ok")), out.get("message", ""))
    else:
        print("  SKIP  ffmpeg edit (no mira video on disk)")

    # ── 6. Live crew commands (fast agents) ──
    section("6) LIVE CREW COMMANDS")
    live_cmds = [
        ("bring coffee and bottles", "waiter"),
        ("weather today", "weather"),
        ("Mira make a short about coffee", "mira"),  # may background — just check routed
    ]
    for msg, expect_agent in live_cmds:
        try:
            status, data = http_json("POST", "/api/crew/command", {"message": msg}, timeout=90)
            aid = data.get("agent_id") or data.get("agent")
            ok(
                f"crew cmd → {expect_agent}",
                status == 200 and data.get("ok") and aid == expect_agent,
                f"agent={aid} msg={str(data.get('message') or data.get('response') or '')[:100]}",
            )
        except Exception as exc:
            ok(f"crew cmd → {expect_agent}", False, str(exc))

    # ── 7. Live mira / hunt / fast / status ──
    section("7) LIVE MIRA / HUNT / FAST / TTS")
    try:
        status, data = http_json("GET", "/api/mira-status")
        ok("mira-status shape", status == 200 and isinstance(data, dict), str(list(data.keys())[:8]))
    except Exception as exc:
        ok("mira-status", False, str(exc))

    try:
        status, data = http_json("GET", "/api/hunt-status")
        ok("hunt-status shape", status == 200 and isinstance(data, dict))
    except Exception as exc:
        ok("hunt-status", False, str(exc))

    try:
        # Short mute video via /api/mira — poll briefly
        status, data = http_json(
            "POST",
            "/api/mira",
            {
                "message": "make a mute 8 second short about blue ocean waves",
                "aspect": "9:16",
                "duration_sec": 8,
                "audio_mode": "mute",
            },
            timeout=30,
        )
        ok("mira start job", status == 200 and (data.get("ok") or data.get("started") or data.get("job_id") or "message" in data), str(data)[:160])
        # poll up to ~90s
        done = False
        last = {}
        for i in range(30):
            time.sleep(3)
            _, last = http_json("GET", "/api/mira-status", timeout=10)
            st = str(last.get("status") or last.get("state") or "").lower()
            if st in ("done", "complete", "completed", "idle", "ready") and last.get("result"):
                done = True
                break
            if st in ("error", "failed"):
                break
            if not last.get("running") and i > 2 and (last.get("message") or last.get("result")):
                # some implementations clear running when done
                if "fail" in str(last.get("message") or "").lower() or last.get("error"):
                    break
                if last.get("video_path") or last.get("path") or last.get("result"):
                    done = True
                    break
        ok("mira job progress/poll", done or bool(last.get("running") is False), str(last)[:200])
    except Exception as exc:
        ok("mira live job", False, str(exc))

    try:
        status, data = http_json("POST", "/api/fast", {"message": "what time is it"}, timeout=30)
        ok("fast router", status == 200, str(data)[:120])
    except Exception as exc:
        ok("fast router", False, str(exc))

    try:
        status, data = http_json("GET", "/api/briefing", timeout=60)
        ok("briefing", status == 200, str(data)[:120])
    except Exception as exc:
        ok("briefing", False, str(exc))

    # ── 8. Unit test suites ──
    section("8) UNITTEST SUITES")
    suite_names = [
        "tests.test_elevenlabs_login",
        "tests.test_api_env_gate",
        "tests.test_calendar_smoke",
        "tests.test_mail_choice_creds_smoke",
        "tests.test_identity_autonomy_smoke",
        "tests.test_scoped_batch",
    ]
    for name in suite_names:
        try:
            loader = unittest.defaultTestLoader
            suite = loader.loadTestsFromName(name)
            res = unittest.TextTestRunner(verbosity=0, stream=open("NUL", "w")).run(suite)
            ok(
                name,
                res.wasSuccessful(),
                f"tests={res.testsRun} fail={len(res.failures)} err={len(res.errors)}",
            )
            for f in res.failures[:2]:
                print(f"       failure: {f[0]}")
            for e in res.errors[:2]:
                print(f"       error: {e[0]}")
        except Exception as exc:
            ok(name, False, str(exc))

    # Mira smoke functions (not TestCase)
    section("9) MIRA SMOKE FUNCTIONS")
    import tests.test_mira_smoke as ms

    for fn_name in sorted(dir(ms)):
        if not fn_name.startswith("test_"):
            continue
        try:
            getattr(ms, fn_name)()
            ok(f"mira_smoke.{fn_name}", True)
        except Exception as exc:
            ok(f"mira_smoke.{fn_name}", False, str(exc))

    # ── 9b. Town / static assets ──
    section("10) HUD / TOWN STATIC")
    for path in (
        "/static/js/town.js?v=58",
        "/static/js/app.js?v=58",
        "/static/css/town.css?v=58",
    ):
        try:
            req = urllib.request.Request(BASE + path)
            with urllib.request.urlopen(req, timeout=10) as r:
                body = r.read()
                ok(f"static {path.split('?')[0]}", r.status == 200 and len(body) > 500, f"bytes={len(body)}")
        except Exception as exc:
            ok(f"static {path}", False, str(exc))

    try:
        req = urllib.request.Request(BASE + "/static/js/town.js?v=58")
        with urllib.request.urlopen(req, timeout=10) as r:
            js = r.read().decode("utf-8", errors="replace")
        ok("town has CAFE", "CAFE" in js)
        ok("town has ARCADE", "ARCADE" in js)
        ok("town has CINEMA", "CINEMA" in js)
        ok("town W=960", "W = 960" in js or "const W = 960" in js)
    except Exception as exc:
        ok("town content check", False, str(exc))

    # ── Credentials (no secrets printed) ──
    section("11) CREDENTIALS / KEYS PRESENCE")
    try:
        from jarvis.tools.credentials import get_user_email
        from jarvis.mira.pexels import configured as pexels_ok

        em = get_user_email() or ""
        ok("login email set", "@" in em, "present" if em else "MISSING")
        ok("pexels configured", pexels_ok(), "yes" if pexels_ok() else "no key — stock fallback")
    except Exception as exc:
        ok("creds check", False, str(exc))

    elapsed = time.perf_counter() - t0
    section("SUMMARY")
    print(f"PASS={passes}  FAIL={len(fails)}  elapsed={elapsed:.1f}s")
    if fails:
        print("FAILURES:")
        for f in fails:
            print(f"  - {f}")
    else:
        print("ALL CHECKS PASSED")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
