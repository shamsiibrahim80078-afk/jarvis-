"""Deep E2E smoke: hunt intent, mira parse/edit/clip, login units, ffmpeg."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

fails: list[str] = []


def check(name: str, cond: object, detail: str = "") -> None:
    ok = bool(cond)
    print(("PASS" if ok else "FAIL"), name, (detail[:160] if detail else ""))
    if not ok:
        fails.append(name)


def main() -> int:
    from jarvis.tools.api_intent import is_api_hunt_intent, wants_env_save
    from jarvis.tools.api_pipeline import is_batch_api_command
    from jarvis.tools.api_hunter import detect_provider
    from jarvis.crew.registry import pick_agent_for_task

    check("hunt groq key", is_api_hunt_intent("get me groq api key"))
    check("hunt url groq", is_api_hunt_intent("get api from https://console.groq.com/keys"))
    check("hunt url not batch", not is_batch_api_command("get api from https://console.groq.com/keys"))
    check("batch sheet still", is_batch_api_command("get all apis from sheet"))
    check("detect groq url", detect_provider("get api from https://console.groq.com/keys") == "groq")
    check("crew hunter route", pick_agent_for_task("get groq api key") == "hunter")
    check("crew mira not waiter", pick_agent_for_task("Mira make a short about coffee") == "mira")
    check(
        "env save gate",
        wants_env_save("save groq api to .env") and not wants_env_save("get me groq api key"),
    )

    from tests.test_elevenlabs_login import ElevenLabsFlowTests, EmailFillGuardTests

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ElevenLabsFlowTests)
    suite2 = unittest.defaultTestLoader.loadTestsFromTestCase(EmailFillGuardTests)
    res = unittest.TextTestRunner(verbosity=0).run(unittest.TestSuite([suite, suite2]))
    check(
        "elevenlabs login units",
        res.wasSuccessful(),
        f"fail={len(res.failures)} err={len(res.errors)}",
    )

    from jarvis.tools.mira_tool import parse_mira_command, is_mira_generate_intent, is_youtube_watch_intent
    from jarvis.mira.edit import parse_edit_command, edit_video, latest_video, is_edit_intent
    from jarvis.mira.clipping import looks_like_clip_command, extract_clip_topic_hint

    p = parse_mira_command("make a youtube shorts about cooking pasta funny")
    check(
        "mira shorts parse",
        bool(
            p
            and p.get("action") == "video"
            and p.get("format") == "youtube_shorts"
            and p.get("mood") == "funny"
        ),
        str(p),
    )
    check("mira generate intent", is_mira_generate_intent("make a video about cats"))
    check("yt search not mira", is_youtube_watch_intent("search for funny cats on youtube"))
    check("yt search not generate", not is_mira_generate_intent("search for funny cats on youtube"))

    ed = parse_edit_command("crop last video to shorts")
    check(
        "edit crop parse",
        bool(ed and ed.get("action") == "edit" and ed.get("aspect") == "9:16"),
        str(ed),
    )
    check("edit mute intent", is_edit_intent("mute the video audio"))
    check("clip command", looks_like_clip_command("clip this video into shorts"))
    check("clip topic", bool(extract_clip_topic_hint("clip video about coffee steam")))

    # remake mood
    rem = parse_edit_command("make it funny")
    check(
        "remake funny",
        bool(rem and rem.get("action") == "remake" and rem.get("mood") == "funny"),
        str(rem),
    )

    vid = latest_video()
    if vid:
        out = edit_video(source=str(vid), aspect="9:16", duration_sec=3, mute=True, label="e2e")
        check(
            "ffmpeg edit vertical mute",
            bool(out.get("ok") and Path(out.get("video_path", "")).is_file()),
            out.get("message", ""),
        )
        out2 = edit_video(source=str(vid), speed=2.0, duration_sec=2, label="e2e_spd")
        check("ffmpeg edit speed", bool(out2.get("ok")), out2.get("message", ""))
        out3 = edit_video(source=str(vid), text="Hook line", duration_sec=2, label="growth_e2e")
        check("ffmpeg edit caption", bool(out3.get("ok")), out3.get("message", ""))
    else:
        print("SKIP ffmpeg edit — no mira videos yet")

    from jarvis.crew import dispatch
    from jarvis.tools import mira_jobs, hunt_bus

    check("dispatch runners", set(dispatch._RUNNERS) >= {"mira", "hunter", "waiter", "weather"})
    check("mira_jobs status", isinstance(mira_jobs.get_status(), dict))
    check("hunt_bus status", isinstance(hunt_bus.get_status(), dict))

    from jarvis.tools.credentials import get_user_email

    em = get_user_email() or ""
    check("login email configured", "@" in em, "email set" if em else "MISSING — live hunt needs creds")

    # Mira smoke asserts (plain functions)
    import tests.test_mira_smoke as ms

    for fn_name in dir(ms):
        if not fn_name.startswith("test_"):
            continue
        fn = getattr(ms, fn_name)
        try:
            fn()
            check(f"mira_smoke.{fn_name}", True)
        except Exception as exc:
            check(f"mira_smoke.{fn_name}", False, str(exc))

    res2 = unittest.TextTestRunner(verbosity=0).run(
        unittest.defaultTestLoader.loadTestsFromName("tests.test_api_env_gate")
    )
    check(
        "api_env_gate suite",
        res2.wasSuccessful(),
        f"fail={len(res2.failures)} err={len(res2.errors)}",
    )

    # Live HTTP: hunt status + mira status (no full browser hunt)
    try:
        import urllib.request

        for path in ("/api/health", "/api/hunt-status", "/api/mira-status", "/api/crew/state"):
            with urllib.request.urlopen(f"http://127.0.0.1:8765{path}", timeout=8) as r:
                check(f"http {path}", r.status == 200, str(r.status))
    except Exception as exc:
        check("http endpoints", False, str(exc))

    print("\n==== SUMMARY ====")
    print("FAILS:", fails or "none")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
