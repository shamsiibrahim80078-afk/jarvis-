"""Creative video quality checks (honest, non-semantic)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def _probe_duration(path: Path) -> float:
    try:
        from jarvis.mira.fast_encode import _probe_duration as _pd

        return float(_pd(path) or 0.0)
    except Exception:
        return 0.0


def _probe_wh(path: Path) -> tuple[int, int]:
    try:
        import json
        import subprocess

        from jarvis.mira.fast_encode import _ffmpeg

        ff = _ffmpeg()
        # ffprobe sits next to ffmpeg typically
        probe = ff.replace("ffmpeg", "ffprobe")
        cmd = [
            probe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            str(path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if proc.returncode != 0:
            return 0, 0
        data = json.loads(proc.stdout or "{}")
        streams = data.get("streams") or []
        if not streams:
            return 0, 0
        return int(streams[0].get("width") or 0), int(streams[0].get("height") or 0)
    except Exception:
        return 0, 0


def _aspect_bucket(w: int, h: int) -> str:
    if w <= 0 or h <= 0:
        return ""
    r = w / h
    if r < 0.7:
        return "9:16"
    if r > 1.4:
        return "16:9"
    return "1:1"


def validate_creative_output(
    result: dict[str, Any],
    *,
    expected_aspect: str,
    expected_duration_sec: int,
    planned_scene_ids: list[str],
    narrations: list[str],
) -> dict[str, Any]:
    """Structural validation — does not claim perfect semantic visual quality."""
    issues: list[str] = []
    path = Path(str(result.get("video_path") or ""))
    if not result.get("ok"):
        return {
            "ok": False,
            "issues": ["generate_failed"],
            "message": result.get("message") or "generation failed",
        }
    if not path.is_file():
        issues.append("missing_file")
    else:
        sz = path.stat().st_size
        if sz < 20_000:
            issues.append("file_too_small")
        dur = _probe_duration(path)
        if dur < 2.0:
            issues.append("duration_too_short")
        target = max(8, int(expected_duration_sec or 30))
        if dur > 0 and abs(dur - target) > max(12.0, target * 0.75):
            issues.append("duration_far_from_request")
        w, h = _probe_wh(path)
        got = _aspect_bucket(w, h)
        want = (expected_aspect or "").strip()
        if want in ("9:16", "16:9") and got and got != want:
            issues.append(f"aspect_mismatch want={want} got={got}")

    handled = list(result.get("scenes_handled") or [])
    # Prefer explicit generation-expectation list (Phase 5A HF cap honesty)
    expected = list(
        result.get("scenes_expected_for_generation") or planned_scene_ids or []
    )
    if expected and handled:
        missing = [s for s in expected if s not in handled]
        if missing:
            issues.append(f"scenes_missing={missing[:4]}")
    elif expected and not handled:
        issues.append("scenes_not_reported")

    # If a full plan was larger than what was submitted, require honest deferral metadata
    deferred = list(result.get("scenes_deferred_by_cap") or [])
    planned_full = int(result.get("scenes_planned_count") or 0)
    submitted = int(result.get("scenes_submitted_count") or 0)
    if planned_full and submitted and planned_full > submitted and not deferred:
        issues.append("scene_cap_not_reported")

    # Duplicate narration check
    norms = [re.sub(r"\s+", " ", (n or "").strip().lower()) for n in narrations if (n or "").strip()]
    if len(norms) >= 3 and len(set(norms)) == 1:
        issues.append("narration_fully_duplicated")

    # Honesty: legacy collage must not claim neural video
    prov = str(result.get("provider") or "")
    kind = str(result.get("generation_kind") or "")
    if "legacy" in prov or kind == "legacy_stock_collage":
        if result.get("is_neural_video"):
            issues.append("false_neural_claim")
    if kind == "neural_video" and not result.get("is_neural_video"):
        issues.append("neural_flag_inconsistent")
    # remote_t2v may only claim neural when a real file exists
    if result.get("is_neural_video"):
        if kind not in ("remote_t2v", "neural_video") and "legacy" not in kind:
            pass  # allow future neural kinds
        if kind == "remote_t2v" and (not path.is_file() or path.stat().st_size < 8_000):
            issues.append("false_neural_claim")
        if kind == "legacy_stock_collage":
            issues.append("false_neural_claim")

    ok = not issues
    return {
        "ok": ok,
        "issues": issues,
        "message": "quality_ok" if ok else f"quality_issues:{','.join(issues[:6])}",
    }
