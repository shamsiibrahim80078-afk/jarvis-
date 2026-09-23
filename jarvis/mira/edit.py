"""Post-produce Mira editor — trim, crop, mute, speed, volume, text.

Uses ffmpeg only. Operates on last Mira video unless a path is given.
"""

from __future__ import annotations

import re
import subprocess
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
VIDEOS = ROOT / "data" / "mira" / "videos"


def _ffmpeg() -> str:
    from jarvis.mira.fast_encode import _ffmpeg as ff

    return ff()


def latest_video() -> Path | None:
    if not VIDEOS.is_dir():
        return None
    files = sorted(VIDEOS.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def resolve_source(path: str | None = None) -> Path | None:
    if path:
        p = Path(path).expanduser()
        if p.is_file():
            return p.resolve()
        cand = VIDEOS / Path(path).name
        if cand.is_file():
            return cand.resolve()
    return latest_video()


def _run_ff(cmd: list[str], timeout: float = 240.0) -> tuple[bool, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    except Exception as exc:
        return False, str(exc)
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", errors="ignore")[-300:]
        return False, err
    return True, ""


def edit_video(
    *,
    source: str | None = None,
    aspect: str | None = None,
    duration_sec: float | None = None,
    start_sec: float = 0.0,
    speed: float | None = None,
    mute: bool = False,
    volume: float | None = None,
    text: str | None = None,
    label: str = "edit",
) -> dict[str, Any]:
    """Apply one or more edits. Returns new mp4 path."""
    src = resolve_source(source)
    if not src:
        return {"ok": False, "message": "No video found to edit. Generate one first."}

    VIDEOS.mkdir(parents=True, exist_ok=True)
    out = VIDEOS / f"edit_{label}_{uuid.uuid4().hex[:8]}.mp4"
    ff = _ffmpeg()

    vf_parts: list[str] = []
    af_parts: list[str] = []

    # Aspect / reframe
    if aspect:
        vertical = aspect in ("9:16", "vertical", "shorts", "reel", "story", "tiktok")
        ow, oh = (1080, 1920) if vertical else (1920, 1080)
        vf_parts.append(
            f"scale={ow}:{oh}:force_original_aspect_ratio=increase,crop={ow}:{oh}"
        )
        aspect_out = "9:16" if vertical else "16:9"
    else:
        aspect_out = "keep"
        vf_parts.append("null")  # placeholder replaced below

    # Speed (video + audio)
    spd = None
    if speed is not None:
        try:
            spd = max(0.25, min(4.0, float(speed)))
        except (TypeError, ValueError):
            spd = None
    if spd and abs(spd - 1.0) > 0.01:
        # setpts for video; atempo for audio (chain if needed)
        vf_parts.append(f"setpts={1.0 / spd:.6f}*PTS")
        # atempo only supports 0.5–2.0 per filter — chain
        remain = spd
        while remain > 2.0 + 1e-6:
            af_parts.append("atempo=2.0")
            remain /= 2.0
        while remain < 0.5 - 1e-6:
            af_parts.append("atempo=0.5")
            remain /= 0.5
        af_parts.append(f"atempo={remain:.4f}")

    if text:
        safe = re.sub(r"[^A-Za-z0-9 .!?_\-]", "", text)[:48]
        if safe:
            font = "C\\:/Windows/Fonts/arialbd.ttf"
            if not Path("C:/Windows/Fonts/arialbd.ttf").is_file():
                font = "C\\:/Windows/Fonts/arial.ttf"
            # Growth hooks sit high (viral Shorts style); normal captions near bottom
            y_expr = "h*0.12" if (label or "").lower().startswith("growth") else "h*0.85"
            size = 56 if (label or "").lower().startswith("growth") else 48
            vf_parts.append(
                f"drawtext=fontfile={font}:text='{safe}':fontsize={size}:"
                f"fontcolor=white:borderw=3:bordercolor=black@0.7:"
                f"x=(w-text_w)/2:y={y_expr}:box=1:boxcolor=black@0.5:boxborderw=14"
            )

    # Clean vf: remove lone null if we added real filters
    vf_parts = [p for p in vf_parts if p != "null"]
    if not vf_parts:
        vf_parts = ["fps=30"]
    else:
        if not any(p.startswith("fps=") for p in vf_parts):
            vf_parts.append("fps=30")

    if mute:
        af_parts = []  # drop audio later
    elif volume is not None:
        try:
            vol = max(0.0, min(3.0, float(volume)))
            af_parts.insert(0, f"volume={vol:.3f}")
        except (TypeError, ValueError):
            pass

    cmd = [ff, "-y"]
    if start_sec and float(start_sec) > 0:
        cmd += ["-ss", f"{float(start_sec):.2f}"]
    cmd += ["-i", str(src)]
    if duration_sec and float(duration_sec) > 0:
        cmd += ["-t", f"{float(duration_sec):.2f}"]

    cmd += ["-vf", ",".join(vf_parts)]
    cmd += [
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-b:v",
        "12000k",
        "-pix_fmt",
        "yuv420p",
    ]

    if mute:
        cmd += ["-an"]
    elif af_parts:
        cmd += ["-af", ",".join(af_parts), "-c:a", "aac", "-b:a", "128k"]
    else:
        cmd += ["-c:a", "aac", "-b:a", "128k"]

    cmd += ["-movflags", "+faststart", str(out)]

    ok, err = _run_ff(cmd)
    if not ok or not out.is_file() or out.stat().st_size < 10_000:
        # Fallback without drawtext
        if text:
            return edit_video(
                source=str(src),
                aspect=aspect,
                duration_sec=duration_sec,
                start_sec=start_sec,
                speed=speed,
                mute=mute,
                volume=volume,
                text=None,
                label=label,
            )
        return {"ok": False, "message": f"ffmpeg edit failed: {err}"[:280]}

    ops = []
    if aspect:
        ops.append(aspect_out)
    if duration_sec:
        ops.append(f"trim={duration_sec}s")
    if start_sec:
        ops.append(f"start={start_sec}s")
    if spd and abs(spd - 1.0) > 0.01:
        ops.append(f"speed={spd}x")
    if mute:
        ops.append("mute")
    if volume is not None:
        ops.append(f"vol={volume}")
    if text:
        ops.append("text")

    return {
        "ok": True,
        "video_path": str(out.resolve()),
        "source": str(src),
        "aspect": aspect_out,
        "provider": "mira_edit",
        "ops": ops,
        "message": f"Edited video ready: {out.name}" + (f" ({', '.join(ops)})" if ops else ""),
    }


def _is_new_topic_generate(text: str) -> bool:
    """Remake/edit must not steal a brand-new 'about X' generate ask."""
    lower = (text or "").lower()
    if re.search(r"\b(about|showing|featuring)\s+[a-z0-9]", lower) and re.search(
        r"\b(make|create|generate|produce|shoot|render|build|remake|redo|fix)\b",
        lower,
    ):
        # "remake THIS video funny" has no new subject — allow edit
        if re.search(r"\b(this|it|last)\s+(video|clip|one|short|reel)\b", lower):
            return False
        return True
    return False


def is_edit_intent(text: str) -> bool:
    lower = (text or "").lower()
    # "make a mute short about X" is GENERATE with silent audio — not edit last video
    if re.search(
        r"\b(make|create|generate|render|produce|shoot|build)\b.{0,80}\b"
        r"(short|shorts|video|clip|reel|film|movie)\b.{0,40}\b(about|of|for)\b",
        lower,
    ):
        return False
    if _is_new_topic_generate(lower):
        return False
    if re.search(r"\busing\s+my\s+uploads?\b|\bfrom\s+my\s+uploads?\b", lower):
        # Building from uploads is generate/assemble, not post-edit
        if re.search(r"\b(make|create|generate|build|assemble)\b", lower):
            return False
    return bool(
        re.search(
            r"\b(crop|reframe|trim|cut|mute|unmute|slow\s*mo|speed|volume|caption|overlay)\b"
            r".{0,50}\b(video|clip|reel|short|story|this|last|it)\b|"
            r"\b(trim|cut|keep)\s+(?:to\s+)?\d+\s*(?:s|sec|seconds)\b|"
            r"\b(edit)\b.{0,50}\b(video|clip|reel|short|story|this|last|it|crop|trim|mute|speed)\b|"
            r"\b(make\s+(?:it|this|last\s+video)\s+(?:vertical|horizontal|a\s+short|"
            r"shorts|reel|reels|story|stories|tiktok|16:9|9:16|funny|sad|angry|epic|"
            r"faster|slower|mute|silent))\b|"
            r"\b(convert|turn|transform|change)\b.{0,40}\b(into\s+|to\s+)?(shorts?|reels?|stories|"
            r"tiktok|youtube|vertical|horizontal|funny|sad|angry)\b|"
            r"\bcrop\s+(?:to\s+)?(?:shorts?|reels?|stories|vertical|9:16)\b|"
            r"\b(fix|redo|remake)\b.{0,20}\b(this|it|last|video|clip)\b|"
            r"\b(mute|silence)\s+(?:the\s+)?(?:audio|sound|voice|video)\b|"
            r"\b(speed\s*(?:up|down)|slow\s*mo|0\.\d+x|\d+(\.\d+)?x\s*speed)\b",
            lower,
        )
    )


def parse_edit_command(text: str) -> dict[str, Any] | None:
    if not is_edit_intent(text):
        return None
    lower = (text or "").lower()
    from jarvis.mira.formats import apply_format, detect_format, detect_mood

    fmt = detect_format(lower)
    mood = detect_mood(lower)
    applied = apply_format(
        fmt,
        aspect="9:16" if re.search(r"\b(vertical|portrait|9:16)\b", lower) else "16:9",
    )
    aspect = None
    if re.search(r"\b(vertical|portrait|short|shorts|reel|story|tiktok|9:16)\b", lower):
        aspect = "9:16"
    if re.search(r"\b(horizontal|landscape|wide|16:9|youtube video)\b", lower):
        aspect = "16:9"
    if fmt:
        aspect = applied["aspect"]

    dur = None
    dm = re.search(r"(?:trim|cut|keep|to)\s+(\d+)\s*(?:s|sec|seconds)?", lower)
    if dm:
        dur = float(dm.group(1))
    elif fmt == "instagram_stories":
        dur = 15.0

    start = 0.0
    sm = re.search(r"(?:from|start(?:ing)?\s+at)\s+(\d+)\s*(?:s|sec)?", lower)
    if sm:
        start = float(sm.group(1))

    mute = bool(re.search(r"\b(mute|silent|no\s+audio|silence\s+audio)\b", lower))
    speed = None
    if re.search(r"\b(slow\s*mo|slow\s*motion|slower)\b", lower):
        speed = 0.5
    elif re.search(r"\b(faster|speed\s*up|2x)\b", lower):
        speed = 2.0
    spm = re.search(r"(\d+(?:\.\d+)?)\s*x\s*(?:speed)?", lower)
    if spm:
        try:
            speed = float(spm.group(1))
        except ValueError:
            pass

    volume = None
    vm = re.search(r"volume\s*(?:to\s*)?(\d+(?:\.\d+)?)", lower)
    if vm:
        volume = float(vm.group(1))
        if volume > 3:
            volume = volume / 100.0  # allow 50 = 0.5

    text_overlay = None
    tm = re.search(r"(?:caption|text|title)\s+[\"']([^\"']+)[\"']", text or "", re.I)
    if not tm:
        tm = re.search(r"(?:add\s+(?:caption|text|title)\s+)(.+)$", text or "", re.I)
    if tm:
        text_overlay = tm.group(1).strip()[:48]

    if _is_new_topic_generate(lower):
        return None  # Let generate path own the new idea

    remake = bool(
        (
            mood
            and re.search(r"\b(this|it|last|same)\b.{0,20}\b(video|clip|one|short)?\b", lower)
        )
        or re.search(r"\b(fix|redo|remake|regenerate)\b", lower)
        or re.search(r"\b(convert|turn|transform)\b.{0,40}\b(funny|sad|angry|epic|romantic)\b", lower)
    )
    has_edit_ops = any(
        [
            aspect,
            dur,
            start > 0,
            mute,
            speed is not None,
            volume is not None,
            text_overlay,
            re.search(r"\b(crop|reframe|trim|mute|speed|caption)\b", lower),
        ]
    )
    if remake and not has_edit_ops:
        return {
            "action": "remake",
            "aspect": aspect or applied["aspect"],
            "duration_sec": applied.get("duration_sec") or dur,
            "format": applied.get("format"),
            "mood": mood,
            "label": (fmt or "remake").replace("_", "")[:20],
        }

    # Default: if only shorts/reels word, set aspect
    if aspect is None and re.search(r"\b(shorts?|reels?|stories|tiktok)\b", lower):
        aspect = "9:16"

    return {
        "action": "edit",
        "aspect": aspect,
        "duration_sec": dur,
        "start_sec": start,
        "mute": mute,
        "speed": speed,
        "volume": volume,
        "text": text_overlay,
        "format": applied.get("format") if fmt else None,
        "mood": mood,
        "label": (fmt or "edit").replace("_", "")[:20],
    }
