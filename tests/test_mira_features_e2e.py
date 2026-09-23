"""Extra Mira feature E2E: format ask, mood, edit, verify-loop."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

RESULTS = []


def rec(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append({"name": name, "ok": ok, "detail": detail[:400]})
    print(("PASS" if ok else "FAIL"), name, "-", detail[:160])


def main() -> int:
    from jarvis.mira.session import clear_pending, load_pending
    from jarvis.mira.edit import parse_edit_command, edit_video
    from jarvis.mira.agent_loop import verify_result
    from jarvis.mira.last_output import load_last_output
    from jarvis.mira.formats import detect_format, detect_mood, apply_format
    from jarvis.tools.mira_tool import (
        try_mira_command,
        parse_mira_command,
        is_mira_generate_intent,
        is_mira_followup_intent,
    )
    from jarvis.mira.pipeline import run_video
    from jarvis.mira.model import model_identity

    clear_pending()
    t0 = time.perf_counter()

    ident = model_identity()
    rec("model identity", bool(ident.get("model_id")), str(ident.get("tagline", ""))[:120])

    # Format ask flow
    r1 = try_mira_command("make a video about dogs on a beach", background=False)
    rec(
        "format ask on bare topic",
        bool(r1 and "What should I make this for" in r1 and load_pending()),
        (r1 or "")[:100],
    )

    # Format+mood in one prompt skips ask
    clear_pending()
    p = parse_mira_command("make a youtube shorts about cooking pasta funny")
    rec(
        "one-shot shorts+funny parse",
        bool(
            p
            and p.get("format") == "youtube_shorts"
            and p.get("mood") == "funny"
            and not p.get("needs_format")
            and "pasta" in (p.get("topic") or "").lower()
        ),
        str(p)[:200],
    )

    # Edit vs remake
    rec("crop -> edit", parse_edit_command("crop last video to shorts")["action"] == "edit")
    rem = parse_edit_command("make it funny")
    rec("make it funny -> remake", bool(rem and rem["action"] == "remake" and rem.get("mood") == "funny"), str(rem))

    # Followup intent
    clear_pending()
    try_mira_command("make a video about sunset ocean", background=False)
    rec("followup intent while pending", is_mira_followup_intent("2") or is_mira_followup_intent("shorts"))
    clear_pending()

    # Verified mute generate
    out = run_video("scuba diving coral reef", duration_sec=16, aspect="16:9", audio_mode="mute")
    rec(
        "verify-loop scuba",
        bool(out.get("ok") and out.get("agent_verified") and Path(out.get("video_path") or "").is_file()),
        f"attempts={out.get('agent_attempts')} match={out.get('brief_match')}",
    )
    last = load_last_output()
    rec("last_output saved", bool(last and "scuba" in (last.get("topic") or "").lower()), str(last)[:120])

    # Reject off-brief
    bad = verify_result(
        "scuba diving",
        {
            "ok": True,
            "video_path": out.get("video_path"),
            "beats": [
                {
                    "query": "office",
                    "pexels_url": "https://www.pexels.com/video/modern-office-workplace-1/",
                    "line": "hi",
                    "visual": out.get("video_path"),
                }
            ],
        },
    )
    rec("reject office-as-scuba", not bad.get("ok"), str(bad))

    # Edit crop
    vids = list((ROOT / "data/mira/videos").glob("*.mp4"))
    if vids:
        ed = edit_video(aspect="9:16", duration_sec=10, label="report")
        rec("edit crop 9:16", bool(ed.get("ok")), ed.get("message") or "")
    else:
        rec("edit crop 9:16", False, "no videos")

    # Non-media
    rec("ignore weather", not is_mira_generate_intent("whats the weather today"))

    elapsed = time.perf_counter() - t0
    passed = sum(1 for r in RESULTS if r["ok"])
    report = {
        "suite": "mira_features_e2e",
        "passed": passed,
        "total": len(RESULTS),
        "elapsed_sec": round(elapsed, 1),
        "results": RESULTS,
        "identity": ident,
    }
    path = ROOT / "data" / "mira" / "e2e_features_report.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nSUMMARY {passed}/{len(RESULTS)} in {elapsed:.0f}s -> {path}")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
