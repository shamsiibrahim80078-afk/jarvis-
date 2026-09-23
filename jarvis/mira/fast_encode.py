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


def _safe_drawtext(text: str, *, max_len: int = 72) -> str:
    """Sanitize text for ffmpeg drawtext (ASCII-safe, single-quoted)."""
    safe = re.sub(r"[^A-Za-z0-9 .!?_\-,'\"]", "", (text or "").strip())
    safe = safe.replace("'", "").replace('"', "")[:max_len]
    return safe


def resolve_segment_take(
    *,
    planned_duration: float | None,
    src_dur: float,
    vo_dur: float,
    is_image: bool,
    audio_mode: str,
    max_take: float = 28.0,
    smooth: bool = False,
) -> tuple[float, float]:
    """Return (take_sec, stretch_factor) for one beat.

    Planned duration is the target visual length. Narration is never sped up:
    if VO is longer than plan, the segment extends to fit speech.
    Video stretch is capped mildly (≤1.35) — no extreme slow-mo.
    """
    mode = (audio_mode or "voice").strip().lower()
    planned = None
    if planned_duration is not None:
        try:
            planned = float(planned_duration)
        except (TypeError, ValueError):
            planned = None
    if planned is not None and planned > 0:
        take = max(1.5, min(max_take, planned))
        if mode in ("voice", "both") and vo_dur > 0.5:
            take = max(take, min(max_take, vo_dur + 0.2))
        stretch = 1.0
        usable = max(0.8, float(src_dur or 0.0))
        if (not is_image) and usable + 0.35 < take:
            # Mild time-stretch only — prefer covering plan without 2× warping
            stretch = min(1.35, take / usable)
        return take, stretch

    # Legacy heuristic path (unchanged behavior)
    if mode == "voice" and vo_dur > 0:
        take = min(max_take, max(1.8, vo_dur + 0.2))
    elif mode == "both" and vo_dur > 0:
        take = min(max_take, max(1.8, vo_dur + 0.2))
    elif mode == "ambient":
        take = min(5.0, max(2.5, min(src_dur, 4.5)))
    else:
        take = min(8.0, max(2.0, (vo_dur if vo_dur > 0 else 3.5)))
    if is_image and vo_dur > 0 and mode in ("voice", "both"):
        take = max(take, vo_dur + 0.2)
    elif is_image:
        take = min(take, 5.0)

    stretch = 1.0
    if smooth and not is_image and vo_dur > 0 and src_dur > 0.8 and vo_dur > src_dur + 0.35:
        stretch = min(2.0, (vo_dur + 0.15) / max(0.8, src_dur))
        take = vo_dur + 0.2
    return take, stretch


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
    status_out: dict[str, Any] | None = None,
) -> Path:
    """Assemble beats with ffmpeg only — much faster than MoviePy.

    beat keys:
      visual: video/image path
      audio: optional VO mp3 (voice mode)
      heading: optional burnt-in title
      caption: optional narration burn-in (creative Phase 5B)
      duration_sec / planned_duration_sec: optional planned segment length
    audio_mode:
      voice    — TTS track (mute stock audio)
      ambient  — keep scene audio from clips (no VO)
      both     — clip ambient low + VO on top (best-effort)
    fit_mode:
      cover    — fill frame (may crop)
      contain  — full media visible (letterbox)
    smooth:
      better preset, clip from start, stretch short clips to VO (no freeze lag)
    status_out:
      optional dict filled with caption burn metadata
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
    captions_requested = False
    captions_burn_failed = False

    try:
        for i, beat in enumerate(beats):
            if not isinstance(beat, dict):
                continue
            vis = Path(str(beat.get("visual") or ""))
            if not vis.is_file():
                continue
            aud = Path(str(beat.get("audio") or ""))
            heading = re.sub(r"\s+", " ", str(beat.get("heading") or "").strip())
            caption = re.sub(r"\s+", " ", str(beat.get("caption") or "").strip())
            if caption:
                captions_requested = True
            planned_raw = beat.get("duration_sec", beat.get("planned_duration_sec"))
            try:
                planned_dur = float(planned_raw) if planned_raw is not None else None
            except (TypeError, ValueError):
                planned_dur = None

            src_dur = _probe_duration(vis) if vis.suffix.lower() in (
                ".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"
            ) else 8.0
            is_image = vis.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".bmp")
            vo_dur = _audio_duration(aud) if aud.is_file() else 0.0
            take, stretch = resolve_segment_take(
                planned_duration=planned_dur,
                src_dur=float(src_dur or 0.0),
                vo_dur=float(vo_dur or 0.0),
                is_image=is_image,
                audio_mode=mode,
                max_take=max_take,
                smooth=smooth,
            )
            use_planned = planned_dur is not None and planned_dur > 0

            start = 0.0
            if (not smooth) and (not is_image) and (not use_planned) and src_dur > take + 0.8:
                start = max(0.0, (src_dur - take) * 0.2)

            seg = work / f"seg_{i:02d}.mp4"
            vf_base = _vf_fit(ow, oh, int(fps or 30), fit)
            if stretch > 1.05:
                vf_base = f"setpts={stretch:.4f}*PTS,{vf_base}"
            if smooth and take > 0.9:
                fi = min(0.22, take * 0.35)
                fo = max(fi + 0.08, float(take) - min(0.28, take * 0.35))
                vf_base = (
                    f"{vf_base},fade=t=in:st=0:d={fi:.2f},"
                    f"fade=t=out:st={fo:.2f}:d={min(0.25, take * 0.35):.2f}"
                )
            vf = vf_base
            label = caption or (heading if not smooth else "")
            used_drawtext = False
            if label:
                safe = _safe_drawtext(label, max_len=72 if caption else 40)
                if safe:
                    font = "C\\:/Windows/Fonts/arial.ttf"
                    fontsize = 42 if caption else 48
                    vf = (
                        vf_base
                        + f",drawtext=fontfile={font}:text='{safe}':fontsize={fontsize}:"
                        f"fontcolor=white:borderw=2:bordercolor=black@0.6:"
                        f"x=(w-text_w)/2:y=h*0.82:box=1:boxcolor=black@0.45:boxborderw=14"
                    )
                    used_drawtext = True

            def _input_args() -> list[str]:
                if is_image:
                    return ["-loop", "1", "-t", f"{take:.2f}", "-i", str(vis)]
                if stretch > 1.05:
                    return ["-ss", f"{start:.2f}", "-i", str(vis)]
                return ["-ss", f"{start:.2f}", "-t", f"{take:.2f}", "-i", str(vis)]

            def _segment_cmd(vfilt: str) -> list[str]:
                """Encode one beat; vfilt may omit drawtext on caption fallback."""
                c: list[str] = [ff, "-y", *_input_args()]
                if mode == "voice" and aud.is_file():
                    c += ["-i", str(aud)]
                    if use_planned:
                        c += [
                            "-filter_complex",
                            f"[0:v]{vfilt}[v];[1:a]apad=whole_dur={take:.2f}[a]",
                            "-map", "[v]", "-map", "[a]",
                            "-t", f"{take:.2f}",
                            "-c:v", "libx264", "-preset", enc_preset,
                            "-b:v", bitrate or "7000k", "-pix_fmt", "yuv420p",
                            "-r", str(int(fps or 30)),
                            "-c:a", "aac", "-b:a", a_bitrate,
                            str(seg),
                        ]
                    else:
                        c += [
                            "-vf", vfilt,
                            "-map", "0:v:0", "-map", "1:a:0",
                            "-c:v", "libx264", "-preset", enc_preset,
                            "-b:v", bitrate or "7000k", "-pix_fmt", "yuv420p",
                            "-r", str(int(fps or 30)),
                            "-c:a", "aac", "-b:a", a_bitrate, "-shortest",
                            str(seg),
                        ]
                elif mode == "both" and aud.is_file() and not is_image:
                    c += ["-i", str(aud)]
                    if use_planned:
                        c += [
                            "-filter_complex",
                            (
                                f"[0:v]{vfilt}[v];"
                                f"[0:a]volume=0.18,apad=whole_dur={take:.2f}[a0];"
                                f"[1:a]volume=1.0,apad=whole_dur={take:.2f}[a1];"
                                f"[a0][a1]amix=inputs=2:duration=first:dropout_transition=0[a]"
                            ),
                            "-map", "[v]", "-map", "[a]",
                            "-t", f"{take:.2f}",
                            "-c:v", "libx264", "-preset", enc_preset,
                            "-b:v", bitrate or "7000k", "-pix_fmt", "yuv420p",
                            "-c:a", "aac",
                            str(seg),
                        ]
                    else:
                        c += [
                            "-filter_complex",
                            (
                                f"[0:v]{vfilt}[v];"
                                f"[0:a]volume=0.18[a0];[1:a]volume=1.0[a1];"
                                f"[a0][a1]amix=inputs=2:duration=shortest[a]"
                            ),
                            "-map", "[v]", "-map", "[a]",
                            "-c:v", "libx264", "-preset", enc_preset,
                            "-b:v", bitrate or "7000k", "-pix_fmt", "yuv420p",
                            "-c:a", "aac", "-shortest",
                            str(seg),
                        ]
                elif mode == "both" and aud.is_file() and is_image:
                    c += ["-i", str(aud)]
                    if use_planned:
                        c += [
                            "-filter_complex",
                            f"[0:v]{vfilt}[v];[1:a]apad=whole_dur={take:.2f}[a]",
                            "-map", "[v]", "-map", "[a]",
                            "-t", f"{take:.2f}",
                            "-c:v", "libx264", "-preset", enc_preset,
                            "-b:v", bitrate or "7000k", "-pix_fmt", "yuv420p",
                            "-c:a", "aac", "-b:a", a_bitrate,
                            str(seg),
                        ]
                    else:
                        c += [
                            "-vf", vfilt,
                            "-map", "0:v:0", "-map", "1:a:0",
                            "-c:v", "libx264", "-preset", enc_preset,
                            "-b:v", bitrate or "7000k", "-pix_fmt", "yuv420p",
                            "-c:a", "aac", "-b:a", a_bitrate, "-shortest",
                            str(seg),
                        ]
                else:
                    c += [
                        "-vf", vfilt,
                        "-c:v", "libx264", "-preset", enc_preset,
                        "-b:v", bitrate or "7000k", "-pix_fmt", "yuv420p",
                    ]
                    if use_planned:
                        c += ["-t", f"{take:.2f}"]
                    if mode == "mute" or is_image:
                        c += ["-an"]
                    else:
                        c += [
                            "-c:a", "aac", "-b:a", a_bitrate,
                            "-map", "0:v:0", "-map", "0:a:0?",
                        ]
                    c += [str(seg)]
                return c

            try:
                _run(_segment_cmd(vf), timeout=180)
            except RuntimeError:
                # Strip drawtext only; keep planned apad + -t (never -shortest fallback)
                if used_drawtext and caption:
                    captions_burn_failed = True
                _run(_segment_cmd(vf_base), timeout=180)

            if seg.is_file() and seg.stat().st_size > 1000:
                segments.append(seg)

        if not segments:
            raise RuntimeError("fast encode: no segments built")

        lst = work / "concat.txt"
        lst.write_text(
            "".join(f"file '{p.resolve().as_posix()}'\n" for p in segments),
            encoding="utf-8",
        )
        try:
            _run(
                [
                    ff, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", "-movflags", "+faststart", str(out),
                ],
                timeout=60,
            )
        except RuntimeError:
            _run(
                [
                    ff, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c:v", "libx264", "-preset", enc_preset,
                    "-b:v", bitrate or "7000k", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-movflags", "+faststart", str(out),
                ],
                timeout=240,
            )
    finally:
        try:
            for p in work.glob("*"):
                p.unlink(missing_ok=True)
            work.rmdir()
        except Exception:
            pass

    if status_out is not None:
        if captions_requested and captions_burn_failed:
            cap_status = "requested_but_unavailable"
        elif captions_requested:
            cap_status = "burned"
        else:
            cap_status = "off"
        status_out.clear()
        status_out.update(
            {
                "captions_requested": captions_requested,
                "captions_burn_failed": bool(captions_burn_failed),
                "captions": cap_status,
            }
        )

    if not out.is_file() or out.stat().st_size < 1000:
        raise RuntimeError(f"fast encode failed: {out}")
    return out.resolve()
