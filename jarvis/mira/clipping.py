"""YT Shorts clipping — cut long videos into viral vertical clips.

Inspired by the Vugola / “YT Shorts + Clipping” growth play:
take a longer cut, extract multiple punchy Shorts with hook captions,
optionally upload each publicly.
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

ProgressCb = Callable[[str], None]

ROOT = Path(__file__).resolve().parents[2]
CLIPS_DIR = ROOT / "data" / "mira" / "videos" / "clips"


@dataclass
class ClipResult:
    ok: bool
    message: str
    clips: list[Path] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


def _probe_duration(path: Path) -> float:
    try:
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        return float((r.stdout or "0").strip() or 0)
    except Exception:
        return 0.0


def _cut_vertical_clip(
    src: Path,
    dst: Path,
    *,
    start: float,
    duration: float,
) -> bool:
    """Extract a vertical Shorts-safe clip from src."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    vf = (
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,setsar=1"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{start:.2f}",
        "-i",
        str(src),
        "-t",
        f"{duration:.2f}",
        "-vf",
        vf,
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
        "-movflags",
        "+faststart",
        str(dst),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180, check=False)
        return r.returncode == 0 and dst.is_file() and dst.stat().st_size > 1000
    except Exception as e:
        logger.warning("clip cut failed: %s", e)
        return False


def plan_clip_windows(
    total_dur: float,
    *,
    clip_len: float = 18.0,
    max_clips: int = 4,
) -> list[tuple[float, float]]:
    """Evenly sample punchy windows across the source (skip limp intro/outro)."""
    if total_dur <= 0:
        return []
    usable = max(0.0, total_dur - 2.0)
    if usable < clip_len + 1:
        start = min(0.5, max(0.0, total_dur * 0.05))
        dur = min(clip_len, max(5.0, total_dur - start - 0.3))
        return [(start, dur)]

    n = min(max_clips, max(1, int(usable // (clip_len * 0.85))))
    windows: list[tuple[float, float]] = []
    span = usable - clip_len
    for i in range(n):
        t0 = 1.0 + (span * i / max(1, n - 1) if n > 1 else 0)
        windows.append((t0, min(clip_len, total_dur - t0 - 0.2)))
    return windows


def clip_video_to_shorts(
    source: Path | str | None = None,
    *,
    topic_hint: str = "",
    max_clips: int = 4,
    clip_len: float = 18.0,
    burn_captions: bool = True,
    upload: bool = False,
    privacy: str = "public",
    progress: ProgressCb | None = None,
) -> ClipResult:
    """Cut source (or last Mira video) into vertical Shorts clips."""
    from jarvis.mira.edit import edit_video, latest_video

    def prog(m: str) -> None:
        if progress:
            try:
                progress(m)
            except Exception:
                pass

    if source:
        src = Path(source)
    else:
        src = latest_video()
    if not src or not Path(src).is_file():
        return ClipResult(False, "No source video found to clip.")

    src = Path(src)
    dur = _probe_duration(src)
    if dur < 5:
        return ClipResult(False, f"Source too short to clip ({dur:.1f}s).")

    windows = plan_clip_windows(dur, clip_len=clip_len, max_clips=max_clips)
    if not windows:
        return ClipResult(False, "Could not plan clip windows.")

    out_dir = CLIPS_DIR / src.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    hint = (topic_hint or src.stem.replace("_", " ")).strip()[:80]
    captions = [
        re.sub(r"[^A-Za-z0-9 .!?_\-]", "", hint)[:42] or "WATCH THIS",
        "Wait for it",
        "This part hits different",
        "Save this for later",
    ]

    prog(f"Clipping {len(windows)} Shorts from {src.name} ({dur:.0f}s)…")
    clips: list[Path] = []
    for i, (start, length) in enumerate(windows, 1):
        raw = out_dir / f"clip_{i:02d}_raw.mp4"
        final = out_dir / f"clip_{i:02d}.mp4"
        prog(f"Cut {i}/{len(windows)} @ {start:.1f}s…")
        if not _cut_vertical_clip(src, raw, start=start, duration=length):
            continue
        if burn_captions:
            text = captions[(i - 1) % len(captions)]
            edited = edit_video(
                source=str(raw),
                aspect="9:16",
                text=text,
                label="growth",
            )
            if edited.get("ok") and edited.get("path"):
                try:
                    Path(str(edited["path"])).replace(final)
                except Exception:
                    final = Path(str(edited["path"]))
            elif raw.is_file():
                try:
                    raw.replace(final)
                except Exception:
                    final = raw
        else:
            try:
                raw.replace(final)
            except Exception:
                final = raw
        if final.is_file():
            clips.append(final)
            try:
                from jarvis.mira.clip_library import add_clip

                add_clip(final, topic=hint or f"clip {i}", tags=["clip", "shorts"])
            except Exception:
                pass
            try:
                if raw.is_file() and raw.resolve() != final.resolve():
                    raw.unlink(missing_ok=True)
            except Exception:
                pass

    if not clips:
        return ClipResult(False, "Clipping failed — no clips produced.")

    urls: list[str] = []
    if upload:
        from jarvis.mira import youtube_upload as yt

        if not yt.connected():
            return ClipResult(
                True,
                f"Cut {len(clips)} Shorts. Connect YouTube to upload them.",
                clips,
                [],
                {"source": str(src), "needs_auth": True},
            )
        for i, clip in enumerate(clips, 1):
            prog(f"Uploading Short {i}/{len(clips)}…")
            title = f"{hint} — Part {i}" if hint else f"Short clip {i}"
            res = yt.upload_video(
                path=str(clip),
                title=title[:90],
                description=(
                    f"{hint}\n\n#Shorts #viral #fyp\n"
                    "Comment YT if you want the full automation."
                ),
                tags=["shorts", "viral", "clipping", "fyp"],
                privacy=privacy,
                force_shorts=True,
                progress_cb=progress,
            )
            if res.get("ok") and res.get("url"):
                urls.append(str(res["url"]))

    msg = f"Clipped {len(clips)} Shorts from {src.name}."
    if urls:
        msg += " Uploaded:\n" + "\n".join(urls)
    elif upload:
        msg += " Upload finished with no public URLs (check Studio)."
    else:
        msg += f" Saved under {out_dir}."

    return ClipResult(
        True,
        msg,
        clips,
        urls,
        {"source": str(src), "out_dir": str(out_dir), "windows": windows},
    )


def looks_like_clip_command(text: str) -> bool:
    t = (text or "").lower()
    keys = (
        "clip this",
        "clip video",
        "clip the video",
        "clip last",
        "make clips",
        "cut shorts",
        "cut into shorts",
        "clip into shorts",
        "make shorts from",
        "turn into shorts",
        "slice into shorts",
        "clip my video",
        "clip my last",
    )
    if any(k in t for k in keys):
        return True
    # bare "clipping" with last/this/video context
    if "clipping" in t and re.search(r"\b(last|this|video|clip|it)\b", t):
        return True
    return False


def wants_clip_upload(text: str) -> bool:
    t = (text or "").lower()
    return bool(
        re.search(
            r"\b(upload|post|publish)\b|"
            r"\b(and\s+)?(?:upload|post|publish)\b|"
            r"\bto\s+youtube\b",
            t,
        )
    )


def extract_clip_topic_hint(text: str) -> str:
    raw = (text or "").strip()
    m = re.search(r"(?:about|on|of|from)\s+(.+)$", raw, re.I)
    if m:
        hint = m.group(1).strip()
        hint = re.sub(
            r"\b(and\s+)?(upload|post|publish|to\s+youtube|youtube|shorts?)\b",
            " ",
            hint,
            flags=re.I,
        )
        return re.sub(r"\s+", " ", hint).strip(" .,:;-")[:80]
    return ""
