"""E2E Mira office quality gate vs gold reference vid_office_day_1_bc606903.mp4."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)

GOLD = ROOT / "data" / "mira" / "videos" / "vid_office_day_1_bc606903.mp4"


def main() -> int:
    from jarvis.mira.office_routine import _probe_quality, generate_office_episode
    from jarvis.tools.mira_tool import open_mira_media_in_chrome

    report: dict = {"gold": None, "runs": [], "pass": False}
    if GOLD.is_file():
        report["gold"] = _probe_quality(GOLD)
        print("GOLD:", json.dumps(report["gold"], indent=2))
    else:
        print("WARN: gold file missing", GOLD)

    t0 = time.time()
    print("Generating Day 1 English 16:9 Pexels HD…", flush=True)
    out = generate_office_episode(1, duration_sec=45, aspect="16:9", language="en")
    elapsed = round(time.time() - t0, 1)
    run = {
        "elapsed_sec": elapsed,
        "ok": bool(out.get("ok")),
        "message": out.get("message"),
        "qa": out.get("qa"),
        "video_path": out.get("video_path"),
        "notes": out.get("notes", [])[-5:],
    }
    report["runs"].append(run)
    print("RESULT:", json.dumps(run, indent=2, default=str))

    if not out.get("ok"):
        report["pass"] = False
        (ROOT / "data" / "mira" / "e2e_quality_report.json").write_text(
            json.dumps(report, indent=2, default=str), encoding="utf-8"
        )
        print("FAIL quality gate")
        return 1

    path = Path(out["video_path"])
    qa = out.get("qa") or _probe_quality(path)
    gold = report.get("gold") or {}
    # Must be in same league as gold (not 0.9 Mbps trash)
    checks = {
        "long_edge_ge_1280": max(qa.get("width", 0), qa.get("height", 0)) >= 1280,
        "bitrate_ge_4000_or_big_file": (qa.get("bitrate_kbps") or 0) >= 4000
        or (qa.get("bytes") or 0) >= 12_000_000,
        "fps_ge_24": (qa.get("fps") or 0) >= 24,
        "bytes_ge_8mb": (qa.get("bytes") or 0) >= 8_000_000,
        "not_vertical_soft_still_pack": not (
            qa.get("height", 0) > qa.get("width", 0) and (qa.get("bytes") or 0) < 5_000_000
        ),
    }
    report["checks"] = checks
    report["pass"] = all(checks.values()) and bool(out.get("ok"))
    print("CHECKS:", json.dumps(checks, indent=2))
    print("PASS" if report["pass"] else "FAIL")

    if path.is_file():
        try:
            print(open_mira_media_in_chrome(str(path)))
        except Exception as exc:
            print("open failed", exc)

    out_report = ROOT / "data" / "mira" / "e2e_quality_report.json"
    out_report.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("Wrote", out_report)
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
