"""Fast Mira assemble via ffmpeg (skip slow MoviePy frame walks).

Target: office packs in ~1.5–2 minutes when clips are cached / few beats.
Quality: 1080p, balanced bitrate, ultrafast preset (good for stock motion).
"""

from __future__ import annotations

import logging
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any, Sequence

logger = logging.getLogger(__name__)


def _ffmpeg() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def _run(cmd: list[str], timeout: float = 180.0) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "")[-800:]
        raise RuntimeError(f"ffmpeg failed ({proc.returncode}): {err}")


def _probe_duration(path: Path) -> float:
    ff = _ffmpeg()
    proc = subprocess.run([ff, "-i", str(path)], capture_output=True, text=True, timeout=30)
    err = proc.stderr or ""
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", err)
    if not m:
        return 3.0
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def _audio_duration(path: Path) -> float:
    if not path.is_file():
        return 0.0
    return max(0.5, _probe_duration(path))


def _vf_fit(ow: int, oh: int, fps: int, fit_mode: str) -> str:
    """Build scale filter. contain = full image visible; cover = crop fill."""
    fit = (fit_mode or "cover").strip().lower()
    if fit in ("contain", "letterbox", "pad", "fit", "full"):
        return (
            f"scale={ow}:{oh}:force_original_aspect_ratio=decrease,"
            f"pad={ow}:{oh}:(ow-iw)/2:(oh-ih)/2:black,fps={int(fps or 30)}"
        )
    return (
        f"scale={ow}:{oh}:force_original_aspect_ratio=increase,"
        f"crop={ow}:{oh},fps={int(fps or 30)}"
    )


def build_fast_synced_beats(
    beats: Sequence[dict[str, Any]],
    out_mp4: str | Path,
    *,
    fps: int = 30,
    bitrate: str = "7000k",
    out_size=(1920, 1080),
    audio_mode: str = "voice",
    fit_mode: str = "cover",
    preset: str = "ultrafast",
    smooth: bool = False,
) -> Path:
    """Assemble beats with ffmpeg only — much faster than MoviePy.

    beat keys:
      visual: video/image path
      audio: optional VO mp3 (voice mode)
      heading: optional burnt-in title
    audio_mode:
      voice    — TTS track (mute stock audio)
      ambient  — keep scene audio from clips (no VO)
      both     — clip ambient low + VO on top (best-effort)
    fit_mode:
      cover    — fill frame (may crop)
      contain  — full media visible (letterbox)
    smooth:
      better preset, clip from start, stretch short clips to VO (no freeze lag)
    """
    ff = _ffmpeg()
    out = Path(out_mp4)
    out.parent.mkdir(parents=True, exist_ok=True)
    ow = int(out_size[0]) // 2 * 2
    oh = int(out_size[1]) // 2 * 2
    mode = (audio_mode or "voice").strip().lower()
    if mode not in ("voice", "ambient", "both", "mute"):
        mode = "voice"
    fit = (fit_mode or "cover").strip().lower()
    if fit not in ("cover", "contain", "letterbox", "pad", "fit", "full"):
        fit = "cover"
    enc_preset = (preset or "ultrafast").strip() or "ultrafast"
    if smooth and enc_preset == "ultrafast":
        enc_preset = "veryfast"
    max_take = 28.0 if smooth else 12.0
    a_bitrate = "192k" if smooth else "128k"

    work = out.parent / f"_fast_{uuid.uuid4().hex[:10]}"
    work.mkdir(parents=True, exist_ok=True)
    segments: list[Path] = []

    try:
        for i, beat in enumerate(beats):
            if not isinstance(beat, dict):
                continue
            vis = Path(str(beat.get("visual") or ""))
            if not vis.is_file():
                continue
            aud = Path(str(beat.get("audio") or ""))
            heading = re.sub(r"\s+", " ", str(beat.get("heading") or "").strip())

            src_dur = _probe_duration(vis) if vis.suffix.lower() in (
                ".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"
            ) else 8.0
            is_image = vis.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".bmp")
            vo_dur = _audio_duration(aud) if aud.is_file() else 0.0
            if mode == "voice" and aud.is_file():
                take = min(max_take, max(1.8, vo_dur + 0.2))
            elif mode == "both" and aud.is_file():
                take = min(max_take, max(1.8, vo_dur + 0.2))
            elif mode == "ambient":
                take = min(5.0, max(2.5, min(src_dur, 4.5)))
            else:
                take = min(8.0, max(2.0, (vo_dur if aud.is_file() else 3.5)))
            # Images must cover full VO — do not truncate speech
            if is_image and aud.is_file() and mode in ("voice", "both"):
                take = max(take, vo_dur + 0.2)
            elif is_image:
                take = min(take, 5.0)

            start = 0.0
            if (not smooth) and (not is_image) and src_dur > take + 0.8:
                start = max(0.0, (src_dur - take) * 0.2)

            stretch = 1.0
            if smooth and not is_image and aud.is_file() and src_dur > 0.8 and vo_dur > src_dur + 0.35:
                stretch = min(2.0, (vo_dur + 0.15) / max(0.8, src_dur - start))
                take = vo_dur + 0.2

            seg = work / f"seg_{i:02d}.mp4"
            vf_base = _vf_fit(ow, oh, int(fps or 30), fit)
            if stretch > 1.05:
                vf_base = f"setpts={stretch:.4f}*PTS,{vf_base}"
            # Soft edge fades stop white flashes on hard scene cuts (platform tours)
            if smooth and take > 0.9:
                fi = min(0.22, take * 0.35)
                fo = max(fi + 0.08, float(take) - min(0.28, take * 0.35))
                vf_base = f"{vf_base},fade=t=in:st=0:d={fi:.2f},fade=t=out:st={fo:.2f}:d={min(0.25, take * 0.35):.2f}"
            vf = vf_base
            # drawtext is flaky on some Windows builds — never required for success
            if heading and not smooth:
                safe = re.sub(r"[^A-Za-z0-9 .!?_\-]", "", heading)[:40]
                if safe:
                    font = "C\\:/Windows/Fonts/arial.ttf"
                    vf = (
                        vf_base
                        + f",drawtext=fontfile={font}:text='{safe}':fontsize=48:"
                        f"fontcolor=white:borderw=2:bordercolor=black@0.6:"
                        f"x=(w-text_w)/2:y=h*0.78:box=1:boxcolor=black@0.45:boxborderw=16"
                    )

            def _input_args() -> list[str]:
                if is_image:
                    return ["-loop", "1", "-t", f"{take:.2f}", "-i", str(vis)]
                if stretch > 1.05:
                    return ["-ss", f"{start:.2f}", "-i", str(vis)]
                return ["-ss", f"{start:.2f}", "-t", f"{take:.2f}", "-i", str(vis)]

            cmd = [ff, "-y", *_input_args()]

            if mode == "voice" and aud.is_file():
                cmd += ["-i", str(aud)]
                cmd += [
                    "-vf",
                    vf,
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a:0",
                    "-c:v",
                    "libx264",
                    "-preset",
                    enc_preset,
                    "-b:v",
                    bitrate or "7000k",
                    "-pix_fmt",
                    "yuv420p",
                    "-r",
                    str(int(fps or 30)),
                    "-c:a",
                    "aac",
                    "-b:a",
                    a_bitrate,
                    "-shortest",
                    str(seg),
                ]
            elif mode == "both" and aud.is_file() and not is_image:
                # VO dominant + quiet ambient from clip if present
                cmd += ["-i", str(aud)]
                cmd += [
                    "-filter_complex",
                    (
                        f"[0:v]{vf_base}[v];"
                        f"[0:a]volume=0.18[a0];[1:a]volume=1.0[a1];"
                        f"[a0][a1]amix=inputs=2:duration=shortest[a]"
                    ),
                    "-map",
                    "[v]",
                    "-map",
                    "[a]",
                    "-c:v",
                    "libx264",
                    "-preset",
                    enc_preset,
                    "-b:v",
                    bitrate or "7000k",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-shortest",
                    str(seg),
                ]
            elif mode == "both" and aud.is_file() and is_image:
                # Images have no ambient track — VO only (same as voice)
                cmd += ["-i", str(aud)]
                cmd += [
                    "-vf",
                    vf,
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a:0",
                    "-c:v",
                    "libx264",
                    "-preset",
                    enc_preset,
                    "-b:v",
                    bitrate or "7000k",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-b:a",
                    a_bitrate,
                    "-shortest",
                    str(seg),
                ]
            else:
                # ambient / mute
                cmd += [
                    "-vf",
                    vf,
                    "-c:v",
                    "libx264",
                    "-preset",
                    enc_preset,
                    "-b:v",
                    bitrate or "7000k",
                    "-pix_fmt",
                    "yuv420p",
                ]
                if mode == "mute" or is_image:
                    cmd += ["-an"]
                else:
                    cmd += ["-c:a", "aac", "-b:a", a_bitrate, "-map", "0:v:0", "-map", "0:a:0?"]
                cmd += [str(seg)]

            try:
                _run(cmd, timeout=180)
            except RuntimeError:
                # Reliable fallback: no drawtext, correct image inputs
                cmd2 = [ff, "-y", *_input_args()]
                if aud.is_file() and mode in ("voice", "both"):
                    cmd2 += [
                        "-i",
                        str(aud),
                        "-vf",
                        vf_base,
                        "-map",
                        "0:v:0",
                        "-map",
                        "1:a:0",
                        "-c:v",
                        "libx264",
                        "-preset",
                        enc_preset,
                        "-b:v",
                        bitrate or "7000k",
                        "-pix_fmt",
                        "yuv420p",
                        "-c:a",
                        "aac",
                        "-shortest",
                        str(seg),
                    ]
                else:
                    cmd2 += [
                        "-vf",
                        vf_base,
                        "-c:v",
                        "libx264",
                        "-preset",
                        enc_preset,
                        "-b:v",
                        bitrate or "7000k",
                        "-pix_fmt",
                        "yuv420p",
                        "-an",
                        str(seg),
                    ]
                _run(cmd2, timeout=180)

            if seg.is_file() and seg.stat().st_size > 1000:
                segments.append(seg)

        if not segments:
            raise RuntimeError("fast encode: no segments built")

        lst = work / "concat.txt"
        lst.write_text(
            "".join(f"file '{p.resolve().as_posix()}'\n" for p in segments),
            encoding="utf-8",
        )
        # Prefer stream copy (seconds); fall back to re-encode if needed
        try:
            _run(
                [
                    ff,
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(lst),
                    "-c",
                    "copy",
                    "-movflags",
                    "+faststart",
                    str(out),
                ],
                timeout=60,
            )
        except RuntimeError:
            _run(
                [
                    ff,
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(lst),
                    "-c:v",
                    "libx264",
                    "-preset",
                    enc_preset,
                    "-b:v",
                    bitrate or "7000k",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-movflags",
                    "+faststart",
                    str(out),
                ],
                timeout=240,
            )
    finally:
        # cleanup temp (best effort)
        try:
            for p in work.glob("*"):
                p.unlink(missing_ok=True)
            work.rmdir()
        except Exception:
            pass

    if not out.is_file() or out.stat().st_size < 1000:
        raise RuntimeError(f"fast encode failed: {out}")
    return out.resolve()
