"""Retention polish for Shorts — zoom punches + end-screen follow card."""

from __future__ import annotations

import logging
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
VIDEOS = ROOT / "data" / "mira" / "videos"


def _ffmpeg() -> str:
    from jarvis.mira.fast_encode import _ffmpeg as ff

    return ff()


def _probe_duration(path: Path) -> float:
    try:
        from jarvis.mira.fast_encode import _probe_duration

        return float(_probe_duration(path) or 0)
    except Exception:
        return 0.0


def _safe(text: str, limit: int = 40) -> str:
    t = re.sub(r"[^A-Za-z0-9 .!?_\-]", "", (text or "").strip())
    return re.sub(r"\s+", " ", t).strip()[:limit]


def polish_for_retention(
    source: str | Path,
    *,
    hook: str = "",
    end_card: str = "Follow for Part 2",
    label: str = "retention",
) -> dict[str, Any]:
    """Apply mild zoom punches + hook + end card. Falls back to edit_video on failure."""
    src = Path(source)
    if not src.is_file():
        return {"ok": False, "message": "No source for retention polish."}

    VIDEOS.mkdir(parents=True, exist_ok=True)
    out = VIDEOS / f"edit_{label}_{uuid.uuid4().hex[:8]}.mp4"
    dur = _probe_duration(src) or 18.0
    hook_s = _safe(hook, 36)
    end_s = _safe(end_card, 36) or "Follow for Part 2"
    font = "C\\:/Windows/Fonts/arialbd.ttf"
    if not Path("C:/Windows/Fonts/arialbd.ttf").is_file():
        font = "C\\:/Windows/Fonts/arial.ttf"

    end_start = max(0.5, dur - 1.4)
    # Vertical safe — skip fragile zoompan (breaks drawtext / output on Windows)
    vf_parts = [
        "scale=1080:1920:force_original_aspect_ratio=increase",
        "crop=1080:1920",
        "setsar=1",
    ]
    if hook_s:
        hook_esc = hook_s.replace("\\", "\\\\").replace(":", "\\:").replace("'", "").replace("%", "\\%")
        vf_parts.append(
            f"drawtext=fontfile={font}:text='{hook_esc}':fontsize=56:"
            f"fontcolor=white:borderw=3:bordercolor=black@0.7:"
            f"x=(w-text_w)/2:y=h*0.12:box=1:boxcolor=black@0.5:boxborderw=14:"
            f"enable='lt(t\\,{end_start:.2f})'"
        )
    end_esc = end_s.replace("\\", "\\\\").replace(":", "\\:").replace("'", "").replace("%", "\\%")
    vf_parts.append(
        f"drawtext=fontfile={font}:text='{end_esc}':fontsize=52:"
        f"fontcolor=white:borderw=3:bordercolor=black@0.8:"
        f"x=(w-text_w)/2:y=(h-text_h)/2:box=1:boxcolor=black@0.65:boxborderw=18:"
        f"enable='gte(t\\,{end_start:.2f})'"
    )

    cmd = [
        _ffmpeg(),
        "-y",
        "-i",
        str(src),
        "-vf",
        ",".join(vf_parts),
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-t",
        f"{min(58.0, dur):.2f}",
        "-movflags",
        "+faststart",
        str(out),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=240, check=False)
        if r.returncode == 0 and out.is_file() and out.stat().st_size > 10_000:
            return {"ok": True, "path": str(out), "message": "Retention polish applied."}
        logger.warning("retention polish ffmpeg failed: %s", (r.stderr or "")[-300:])
    except Exception as exc:
        logger.warning("retention polish error: %s", exc)

    # Fallback: simple hook + end via edit_video twice
    try:
        from jarvis.mira.edit import edit_video

        mid = edit_video(source=str(src), aspect="9:16", text=hook_s or None, label="growth")
        path = str(mid.get("path") or src) if mid.get("ok") else str(src)
        # End card burn as bottom caption if zoom path failed
        end = edit_video(source=path, aspect="9:16", text=end_s, label="endcard")
        if end.get("ok") and end.get("path"):
            return {"ok": True, "path": str(end["path"]), "message": "Retention fallback applied."}
        if mid.get("ok") and mid.get("path"):
            return {"ok": True, "path": str(mid["path"]), "message": "Hook applied (no end card)."}
    except Exception as exc:
        return {"ok": False, "message": str(exc)[:200]}
    return {"ok": False, "message": "Retention polish failed."}
