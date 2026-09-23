"""Daily 9–5 office vlog — Pexels HD motion + fast ffmpeg assemble.

Restores photographic quality of vid_office_day_1_bc606903.mp4:
  1920x1080 · 30fps · high bitrate · real stock motion.

v7: parallel Pexels + ffmpeg (not MoviePy) → target ~1.5–2 min wall-clock.
Audio modes: voice (VO) | ambient (scene sound) | both | mute.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = ROOT / "data" / "mira" / "office_series.json"

SERIES = {
    "title": "Agent Office — 9 to 5",
    "character": "Alex",
    "role": "AI systems engineer",
    "workplace": "modern tech campus office",
}

# Fast pack: 5 beats ≈ target 1.5–2 min when clips cached
WEEK_BEATS: list[list[dict[str, str]]] = [
    # Day 1
    [
        {"t": "listen", "i18n": "listen", "kind": "pexels", "q": "business team meeting modern office open plan", "heading": "LISTEN…", "line": "Listen — a real tech-office 9 to 5. Day one."},
        {"t": "enter", "i18n": "enter", "kind": "pexels", "q": "walking into modern glass office building lobby", "heading": "ENTERING", "line": "Walking into the office now."},
        {"t": "work", "i18n": "work_a", "kind": "pexels", "q": "software engineer coding dual monitors office", "heading": "CODING", "line": "Deep work at the monitors."},
        {"t": "lunch", "i18n": "lunch", "kind": "pexels", "q": "office cafeteria lunch break", "heading": "LUNCH", "line": "Lunch break. Quick reset."},
        {"t": "ship", "i18n": "ship", "kind": "pexels", "q": "developer laptop success office", "heading": "SHIPPED", "line": "Shipped. See you tomorrow."},
    ],
    # Day 2
    [
        {"t": "listen", "i18n": "listen", "kind": "pexels", "q": "young professional office modern workplace", "heading": "LISTEN…", "line": "Day two. Design first — then code."},
        {"t": "work", "i18n": "work_e", "kind": "pexels", "q": "whiteboard brainstorming tech office diagrams", "heading": "DESIGN", "line": "Whiteboard. Sketching the system."},
        {"t": "work2", "i18n": "work_b", "kind": "pexels", "q": "hands typing keyboard code laptop office", "heading": "CODING", "line": "Now coding that design."},
        {"t": "review", "i18n": "work_c", "kind": "pexels", "q": "code review meeting laptop conference room", "heading": "REVIEW", "line": "Code review. Honest feedback."},
        {"t": "outro", "i18n": "outro", "kind": "pexels", "q": "office window sunset city skyline", "heading": "DONE", "line": "Day two done."},
    ],
    # Day 3
    [
        {"t": "listen", "i18n": "listen", "kind": "pexels", "q": "coffee office morning professional", "heading": "LISTEN…", "line": "Midweek. Focus and ship."},
        {"t": "work", "i18n": "work_b", "kind": "pexels", "q": "two developers pair programming laptop", "heading": "CODING", "line": "Pairing on the hard path."},
        {"t": "meeting", "i18n": "meeting", "kind": "pexels", "q": "video conference call office laptop", "heading": "SYNC", "line": "Sync call. Decisions locked."},
        {"t": "ship", "i18n": "ship", "kind": "pexels", "q": "team celebrating project laptop office", "heading": "SOFT LAUNCH", "line": "Soft launch live."},
        {"t": "outro", "i18n": "outro", "kind": "pexels", "q": "person leaving modern office evening", "heading": "DONE", "line": "Midweek shipped."},
    ],
    # Day 4
    [
        {"t": "listen", "i18n": "listen", "kind": "pexels", "q": "developer dashboard charts monitors office", "heading": "LISTEN…", "line": "Day four. Dashboard spiked."},
        {"t": "work", "i18n": "work_d", "kind": "pexels", "q": "debugging code laptop office screens", "heading": "DEBUG", "line": "Debugging. Finding root cause."},
        {"t": "meeting", "i18n": "meeting", "kind": "pexels", "q": "business meeting conference room laptops", "heading": "UPDATE", "line": "Stakeholder update. ETA locked."},
        {"t": "ship", "i18n": "ship", "kind": "pexels", "q": "success laptop office celebration", "heading": "RESOLVED", "line": "All green. Closed."},
        {"t": "outro", "i18n": "outro", "kind": "pexels", "q": "empty modern office evening", "heading": "DONE", "line": "Tough day handled."},
    ],
    # Day 5
    [
        {"t": "listen", "i18n": "listen", "kind": "pexels", "q": "friday office laptop coffee professional", "heading": "LISTEN…", "line": "Friday. Finish and ship."},
        {"t": "work", "i18n": "work_a", "kind": "pexels", "q": "ui design laptop creative office", "heading": "POLISH", "line": "Polish pass on the product."},
        {"t": "meeting", "i18n": "meeting", "kind": "pexels", "q": "product demo presentation office screen", "heading": "DEMO", "line": "Demo time. Keep it short."},
        {"t": "ship", "i18n": "ship", "kind": "pexels", "q": "team celebrating launch office", "heading": "SHIPPED", "line": "Release tagged. Shipped."},
        {"t": "outro", "i18n": "outro", "kind": "pexels", "q": "modern tech campus exterior sunset", "heading": "WEEK DONE", "line": "See you Monday."},
    ],
]


def _load_state() -> dict[str, Any]:
    if STATE_PATH.is_file():
        try:
            data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {"episode_day": 1, "episodes": []}


def _save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def current_episode_day() -> int:
    st = _load_state()
    return max(1, int(st.get("episode_day") or st.get("next_day") or 1))


def beats_for_day(episode_day: int) -> list[dict[str, str]]:
    idx = (max(1, int(episode_day)) - 1) % len(WEEK_BEATS)
    return [dict(b) for b in WEEK_BEATS[idx]]


def build_script(episode_day: int, lang: str = "en") -> str:
    from jarvis.mira.i18n import localize_beats

    beats = localize_beats(beats_for_day(episode_day), lang)
    return " ".join(b.get("line") or "" for b in beats)


def is_office_routine_request(text: str) -> bool:
    lower = (text or "").lower()
    return bool(
        re.search(
            r"\b(office\s*(day|routine|series|vlog|episode)|daily\s+office|9\s*-?\s*to\s*-?\s*5|"
            r"agent\s+office\s+(day|routine|series|vlog|episode)|"
            r"tech\s+office\s+(day|routine)|workday\s+video|"
            r"day\s+in\s+(my\s+)?(the\s+)?(life|office)|corporate\s+vlog)\b",
            lower,
        )
    )


def parse_episode_day(text: str) -> int | None:
    lower = (text or "").lower()
    m = re.search(r"\b(?:day|episode|ep)\s*(\d{1,3})\b", lower)
    if m:
        return max(1, int(m.group(1)))
    if is_office_routine_request(text):
        return current_episode_day()
    return None


def _probe_quality(path: Path) -> dict[str, Any]:
    """Return bitrate/resolution/duration via ffprobe (imageio-ffmpeg binary)."""
    import json as _json
    import subprocess

    try:
        import imageio_ffmpeg

        ff = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return {"ok": False, "error": "no ffmpeg"}
    # ffmpeg -i prints to stderr; use ffprobe-style via ffmpeg
    probe = ff.replace("ffmpeg", "ffprobe") if "ffmpeg" in ff else ff
    cmd = [
        ff,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    # imageio package may only ship ffmpeg — parse stderr from -i
    try:
        proc = subprocess.run(
            [ff, "-i", str(path)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        err = (proc.stderr or "") + (proc.stdout or "")
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    w = h = fps = 0
    v_br = 0.0
    dur = 0.0
    m = re.search(r"Video:.*?(\d{3,5})x(\d{3,5})", err)
    if m:
        w, h = int(m.group(1)), int(m.group(2))
    m = re.search(r"(\d+(?:\.\d+)?)\s*fps", err)
    if m:
        fps = float(m.group(1))
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", err)
    if m:
        dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    m = re.search(r"bitrate:\s*(\d+)\s*kb/s", err)
    if m:
        v_br = float(m.group(1))
    size = path.stat().st_size if path.is_file() else 0
    # Gold reference: 1920x1080, 30fps, ~20000 kb/s, photographic motion
    long_edge = max(w, h)
    ok = (
        size >= 8_000_000
        and long_edge >= 1280
        and (v_br >= 4000 or size / max(dur, 1) >= 200_000)
        and fps >= 24
    )
    return {
        "ok": ok,
        "width": w,
        "height": h,
        "fps": fps,
        "duration_sec": dur,
        "bitrate_kbps": v_br,
        "bytes": size,
        "path": str(path),
    }


def _normalize_audio_mode(audio_mode: str | None) -> str:
    m = (audio_mode or "voice").strip().lower()
    aliases = {
        "vo": "voice",
        "narration": "voice",
        "tts": "voice",
        "listening": "voice",
        "lipsync": "voice",
        "lip-sync": "voice",
        "lip_sync": "voice",
        "bg": "ambient",
        "background": "ambient",
        "scene": "ambient",
        "no_voice": "ambient",
        "novoice": "ambient",
        "silent_vo": "ambient",
        "voice+ambient": "both",
        "vo+ambient": "both",
    }
    m = aliases.get(m, m)
    if m not in ("voice", "ambient", "both", "mute"):
        return "voice"
    return m


def generate_office_episode(
    episode_day: int | None = None,
    *,
    duration_sec: int = 45,
    aspect: str = "16:9",
    language: str = "en",
    audio_mode: str = "voice",
) -> dict[str, Any]:
    """Fast gold-quality office episode: parallel Pexels + ffmpeg assemble.

    Target wall-clock ~1.5–2 min when clips are cached.
    audio_mode: voice | ambient | both | mute
      - voice: TTS narration (default; lip-sync is a later add-on)
      - ambient: keep scene/background sound from clips (no VO)
      - both: quiet ambient under VO
    """
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from jarvis.mira import i18n as i18n_mod
    from jarvis.mira import pexels as pexels_mod
    from jarvis.mira.fast_encode import build_fast_synced_beats
    from jarvis.mira.pipeline import (
        _stem,
        generate_voiceover,
        out_root,
    )

    t0 = time.perf_counter()
    day = max(1, int(episode_day or current_episode_day()))
    lang = i18n_mod.normalize_lang(language)
    voice = i18n_mod.voice_for(lang)
    mode = _normalize_audio_mode(audio_mode)
    raw_beats = beats_for_day(day)

    # Honor duration: shorter target → fewer beats (faster + shorter final)
    dur_req = max(12, min(90, int(duration_sec or 45)))
    if dur_req <= 20:
        raw_beats = raw_beats[:3]
    elif dur_req <= 35:
        raw_beats = raw_beats[:4]
    beats = i18n_mod.localize_beats(raw_beats, lang)

    root = out_root()
    notes: list[str] = [
        f"language={lang}",
        f"voice={voice}",
        f"audio_mode={mode}",
        "mode=pexels_hd_fast_v7",
        f"target_duration_sec={dur_req}",
    ]
    credits: list[dict[str, Any]] = []

    vertical = aspect in ("9:16", "vertical", "shorts", "reel")
    out_w, out_h = (1080, 1920) if vertical else (1920, 1080)
    orient = "portrait" if vertical else "landscape"
    clips_dir = root / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    audio_dir = root / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    if not pexels_mod.configured():
        return {
            "ok": False,
            "status": "error",
            "message": "PEXELS_API_KEY required for gold-quality office motion.",
            "notes": notes,
        }

    # Parallel clip downloads (biggest wait after MoviePy encode)
    queries = [(b.get("q") or "modern tech office workplace") for b in beats]
    fetched = pexels_mod.fetch_videos_parallel(queries, clips_dir, orientation=orient, max_workers=5)
    notes.append(f"pexels_parallel={len(fetched)}")

    need_vo = mode in ("voice", "both")
    synced: list[dict[str, Any]] = []
    script_lines: list[str] = []
    vo_jobs: list[tuple[int, str, str, Path]] = []  # idx, tag, line, path

    for i, b in enumerate(beats):
        line = (b.get("line") or "").strip()
        if not line:
            continue
        script_lines.append(line)
        heading = (b.get("heading") or "").strip()
        tag = str(b.get("t") or "beat")
        q = queries[i] if i < len(queries) else "modern tech office workplace"
        _q, paths, creds = fetched[i] if i < len(fetched) else (q, [], [])
        if not paths:
            notes.append(f"beat {tag}: no pexels video")
            continue
        credits.extend(creds)
        visual = paths[0]
        audio_path = ""
        if need_vo:
            dest = audio_dir / f"{_stem(f'office_d{day}_{lang}_{tag}', 'vo')}.mp3"
            vo_jobs.append((len(synced), tag, line, dest))
        synced.append(
            {
                "tag": tag,
                "kind": "broll",
                "source": "pexels",
                "visual": str(visual),
                "audio": audio_path,
                "line": line,
                "heading": heading,
            }
        )

    # Parallel TTS (skip entirely in ambient/mute)
    if need_vo and vo_jobs:

        def _vo(job: tuple[int, str, str, Path]) -> tuple[int, str, str | None]:
            idx, tag, line, dest = job
            try:
                p = generate_voiceover(line, dest, voice=voice)
                return idx, tag, str(p)
            except Exception as exc:
                return idx, tag, f"ERR:{exc}"

        with ThreadPoolExecutor(max_workers=min(5, len(vo_jobs))) as pool:
            for fut in as_completed([pool.submit(_vo, j) for j in vo_jobs]):
                idx, tag, result = fut.result()
                if result and not str(result).startswith("ERR:"):
                    synced[idx]["audio"] = result
                else:
                    notes.append(f"VO failed {tag}: {result}")

        # Drop beats that needed VO but failed
        if mode == "voice":
            synced = [s for s in synced if s.get("audio")]

    if len(synced) < 3:
        return {
            "ok": False,
            "status": "error",
            "message": f"Need ≥3 motion beats, got {len(synced)}. Check Pexels.",
            "notes": notes,
        }

    if credits:
        notes.append(pexels_mod.attribution_line(credits))

    out_path = root / "videos" / f"{_stem(f'office_vlog_day_{day}_{lang}', 'vid')}.mp4"
    try:
        video_path = build_fast_synced_beats(
            synced,
            out_path,
            fps=30,
            bitrate="16000k",
            out_size=(out_w, out_h),
            audio_mode=mode,
        )
    except Exception as exc:
        return {
            "ok": False,
            "status": "error",
            "message": str(exc)[:240],
            "notes": notes,
            "beats": synced,
        }

    elapsed = time.perf_counter() - t0
    notes.append(f"elapsed_sec={elapsed:.1f}")

    qa = _probe_quality(Path(video_path))
    notes.append(f"qa={qa}")
    if not qa.get("ok"):
        return {
            "ok": False,
            "status": "error",
            "message": (
                f"Quality gate FAILED vs gold (need ≥1080p-ish, high bitrate, ≥8MB). "
                f"Got {qa}"
            )[:320],
            "notes": notes,
            "video_path": str(video_path),
            "qa": qa,
            "beats": synced,
            "elapsed_sec": round(elapsed, 1),
        }

    state = _load_state()
    state["episode_day"] = day + 1
    state["next_day"] = day + 1
    eps = list(state.get("episodes") or [])
    eps.append(
        {
            "day": day,
            "video": str(video_path),
            "title": f"{SERIES['title']} — Day {day}",
            "language": lang,
            "style": "pexels_hd_fast_v7",
            "audio_mode": mode,
            "qa": qa,
            "elapsed_sec": round(elapsed, 1),
            "at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }
    )
    state["episodes"] = eps[-60:]
    _save_state(state)

    mode_note = {
        "voice": "with narration",
        "ambient": "scene ambient only (no VO)",
        "both": "VO + quiet ambient",
        "mute": "silent",
    }.get(mode, mode)

    return {
        "ok": True,
        "status": "ok",
        "action": "create_video",
        "series": SERIES["title"],
        "episode_day": day,
        "next_episode_day": day + 1,
        "language": lang,
        "voice": voice if need_vo else "",
        "audio_mode": mode,
        "topic": f"{SERIES['title']} Day {day} ({lang})",
        "script": " ".join(script_lines),
        "video_path": str(video_path),
        "beats": synced,
        "credits": credits,
        "provider": "mira_office_vlog_v7_fast",
        "aspect": "9:16" if vertical else "16:9",
        "qa": qa,
        "elapsed_sec": round(elapsed, 1),
        "message": (
            f"Office Day {day} ({lang}) ready in {elapsed:.0f}s — {mode_note}: "
            f"{Path(video_path).name}. "
            f"{qa.get('width')}x{qa.get('height')} @ {qa.get('bitrate_kbps')}kb/s. "
            f"Next: Day {day + 1}."
        ),
        "notes": notes,
    }
