"""Mira end-to-end suite — understand → plan → fetch → assemble → brief match.

Run:  .venv\\Scripts\\python.exe tests/test_mira_e2e.py
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

RESULTS: list[dict] = []


def record(name: str, ok: bool, detail: str = "", *, fix_hint: str = "") -> None:
    RESULTS.append(
        {
            "name": name,
            "ok": ok,
            "detail": detail[:500],
            "fix_hint": fix_hint,
        }
    )
    status = "PASS" if ok else "FAIL"
    line = f"[{status}] {name}"
    if detail:
        line += f"\n       {detail[:240]}"
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode("ascii"))


def section(title: str) -> None:
    try:
        print(f"\n=== {title} ===")
    except UnicodeEncodeError:
        print(f"\n=== {title.encode('ascii', 'replace').decode('ascii')} ===")


def test_env() -> None:
    section("1. Environment")
    from jarvis.mira.pexels import configured

    ok_p = configured()
    record("PEXELS_API_KEY configured", ok_p, fix_hint="Add PEXELS_API_KEY to .env")
    import os

    ok_g = bool(os.getenv("GROQ_API_KEY") or os.getenv("OPENROUTER_API_KEY"))
    record("LLM key (Groq/OpenRouter) present", ok_g, "optional but used for director")
    try:
        from jarvis.mira.fast_encode import _ffmpeg

        ff = _ffmpeg()
        record("ffmpeg available", bool(ff), str(ff))
    except Exception as exc:
        import shutil

        ff = shutil.which("ffmpeg")
        record("ffmpeg available", bool(ff), str(ff or exc))


def test_understand() -> None:
    section("2. Free-form understanding (any natural ask)")
    from jarvis.mira.understand import _heuristic_understand
    from jarvis.tools.mira_tool import is_mira_generate_intent, parse_mira_command

    cases = [
        ("yo can u do that thing with dogs on a beach", True, "dogs", False),
        ("i need something cool about cooking pasta", True, "pasta", False),
        ("show me tokyo at night", True, "tokyo", False),
        ("fruits that talk to each other please", True, "fruit", True),
        ("gimme a clip of scuba diving", True, "scuba", False),
        ("make a video about fresh fruits market", True, "fruit", False),
        ("whats the weather today", False, None, False),
        ("open chrome", False, None, False),
    ]
    for raw, want_intent, must, want_dlg in cases:
        intent = is_mira_generate_intent(raw)
        h = _heuristic_understand(raw)
        parsed = parse_mira_command(raw) if intent else None
        ok = intent is want_intent
        if want_intent:
            ok = ok and bool(parsed) and must in (parsed.get("topic") or "").lower()
            if want_dlg:
                ok = ok and bool(parsed.get("character_dialogue") or h.get("character_dialogue"))
        else:
            ok = ok and parsed is None
        record(
            f"understand: {raw[:48]}",
            ok,
            f"intent={intent} topic={(parsed or {}).get('topic') if parsed else None} dlg={h.get('character_dialogue')}",
        )


def test_visual_gate() -> None:
    section("3. Visual fidelity gate (no random/office VO)")
    from jarvis.mira.pexels import visual_relevance

    good = visual_relevance(
        "scuba diving coral reef",
        pexels_url="https://www.pexels.com/video/scuba-divers-exploring-vibrant-coral-reef-34464136/",
    )
    office = visual_relevance(
        "scuba diving coral reef",
        pexels_url="https://www.pexels.com/video/modern-tech-office-workplace-meeting-123/",
    )
    random = visual_relevance(
        "tokyo street night",
        pexels_url="https://www.pexels.com/video/a-woman-yawning-while-lying-on-the-bed-6753380/",
    )
    record("accept on-brief scuba clip", bool(good.get("ok")), str(good))
    record("reject office fallback for scuba", not office.get("ok"), str(office))
    record("reject unrelated yawning clip", not random.get("ok"), str(random))

    # No office pad in source
    src = (ROOT / "jarvis/mira/pexels.py").read_text(encoding="utf-8")
    record(
        "pexels.py has no office workplace fallback",
        "modern tech office workplace" not in src,
    )


def test_fetch_on_brief() -> None:
    section("4. Pexels fetch on-brief")
    from jarvis.mira import pexels as p

    clips = ROOT / "data" / "mira" / "clips"
    clips.mkdir(parents=True, exist_ok=True)
    for topic in ("scuba diving coral reef", "tokyo street at night", "fresh fruits market"):
        paths, creds = p.fetch_videos(topic, clips, count=2, orientation="landscape", brief=topic)
        ok = len(paths) >= 1 and all((c.get("relevance") or {}).get("ok") for c in creds)
        urls = [c.get("pexels_url") for c in creds]
        record(f"fetch on-brief: {topic}", ok, f"n={len(paths)} urls={urls}")


def test_run_videos() -> None:
    section("5. Full video assemble (mute + voice)")
    from jarvis.mira.brief_match import output_match_score
    from jarvis.mira.pipeline import run_video

    jobs = [
        ("scuba diving coral reef", "mute"),
        ("tokyo street at night", "mute"),
        ("fresh fruits market", "voice"),
        ("dogs on a beach", "mute"),
    ]
    for topic, mode in jobs:
        t0 = time.perf_counter()
        try:
            out = run_video(topic, duration_sec=18, aspect="16:9", audio_mode=mode)
        except Exception as exc:
            record(f"run_video[{mode}]: {topic}", False, traceback.format_exc()[-300:])
            continue
        elapsed = time.perf_counter() - t0
        beats = out.get("beats") or []
        m = out.get("brief_match") or output_match_score(topic, beats)
        path = out.get("video_path") or ""
        path_ok = bool(path) and Path(path).is_file() and Path(path).stat().st_size > 50_000
        visual_ok = float(m.get("visual_ratio") or 0) >= 0.6 if m.get("visual_ratio") is not None else True
        # Check no office in pexels urls when topic isn't office
        bad_office = False
        for b in beats:
            url = str(b.get("pexels_url") or b.get("visual") or "").lower()
            if "office" in url and "office" not in topic.lower():
                bad_office = True
        ok = bool(out.get("ok")) and path_ok and (m.get("ok") is not False) and visual_ok and not bad_office
        record(
            f"run_video[{mode}]: {topic}",
            ok,
            f"elapsed={elapsed:.0f}s path={Path(path).name if path else None} match={m} notes={out.get('notes')}",
        )


def test_character_path() -> None:
    section("6. Talking-character path")
    from jarvis.mira.brief_match import needs_fantasy_characters
    from jarvis.mira.pipeline import run_video
    from jarvis.tools.mira_tool import parse_mira_command

    raw = "fruits that talk to each other please"
    ok_need = needs_fantasy_characters("fruits that talk to each other")
    record("needs_fantasy_characters fruits talking", ok_need)
    parsed = parse_mira_command(raw)
    record(
        "parse talking fruits -> character",
        bool(parsed and (parsed.get("character_dialogue") or "fruit" in (parsed.get("topic") or "").lower())),
        str(parsed)[:300],
    )
    t0 = time.perf_counter()
    out = run_video(
        "fruits that talk to each other",
        duration_sec=20,
        aspect="16:9",
        audio_mode="voice",
        force_character=True,
    )
    elapsed = time.perf_counter() - t0
    path = out.get("video_path") or ""
    ok = bool(out.get("ok")) and bool(path) and Path(path).is_file()
    notes = " | ".join(str(n) for n in (out.get("notes") or []))
    # ASCII-safe detail
    detail = (
        f"elapsed={elapsed:.0f}s ok={out.get('ok')} provider={out.get('provider')} "
        f"path={Path(path).name if path else None} msg={out.get('message')}"
    )
    record("run_video character: fruits talking", ok, detail)
    if notes:
        record("character notes captured", True, notes[:240].encode("ascii", "replace").decode("ascii"))


def test_uploads_not_auto() -> None:
    section("7. Uploads not auto-used")
    from jarvis.mira.uploads import resolve_media_paths, wants_user_media
    from jarvis.tools.mira_tool import parse_mira_command

    record(
        "wants_user_media only when asked",
        wants_user_media("make a video about dogs using my uploads")
        and not wants_user_media("make a video about dogs"),
    )
    empty = resolve_media_paths(["nope_missing_xyz.mp4"], use_uploads=True)
    record("explicit missing path does not pad uploads", empty == [], str(empty))
    p1 = parse_mira_command("make a video about dogs")
    p2 = parse_mira_command("make a video about dogs using my uploads")
    record(
        "parse: stock ask does not set use_uploads",
        bool(p1) and not p1.get("use_uploads"),
        str(p1),
    )
    record(
        "parse: uploads ask sets use_uploads",
        bool(p2) and bool(p2.get("use_uploads")),
        str(p2),
    )


def test_parse_to_pipeline_bridge() -> None:
    section("8. parse to create bridge (no execute)")
    from jarvis.tools.mira_tool import parse_mira_command

    p = parse_mira_command("show me tokyo at night")
    ok = p and p.get("action") == "video" and "tokyo" in (p.get("topic") or "").lower()
    record("parse show me tokyo", bool(ok), str(p))


def main() -> int:
    print("MIRA END-TO-END TEST")
    print("=" * 60)
    t0 = time.perf_counter()
    for fn in (
        test_env,
        test_understand,
        test_visual_gate,
        test_fetch_on_brief,
        test_run_videos,
        test_character_path,
        test_uploads_not_auto,
        test_parse_to_pipeline_bridge,
    ):
        try:
            fn()
        except Exception:
            record(fn.__name__, False, traceback.format_exc()[-400:])

    elapsed = time.perf_counter() - t0
    passed = sum(1 for r in RESULTS if r["ok"])
    failed = [r for r in RESULTS if not r["ok"]]
    print("\n" + "=" * 60)
    print(f"SUMMARY: {passed}/{len(RESULTS)} passed in {elapsed:.0f}s")
    if failed:
        print("FAILURES:")
        for r in failed:
            print(f"  - {r['name']}: {r['detail'][:200]}")

    report_path = ROOT / "data" / "mira" / "e2e_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "passed": passed,
        "total": len(RESULTS),
        "elapsed_sec": round(elapsed, 1),
        "failed": failed,
        "results": RESULTS,
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Report written: {report_path}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
