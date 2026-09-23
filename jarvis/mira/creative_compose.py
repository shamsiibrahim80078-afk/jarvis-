"""Compose creative scene plans into a video using existing Mira encoders.

Legacy collage: Pexels clips / Pollinations stills + Edge TTS + fast_encode.
Labeled as legacy — never presented as neural AI video.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any

from jarvis.mira.generation_provider import VideoGenerationRequest

logger = logging.getLogger(__name__)


def _out_size(aspect: str) -> tuple[int, int]:
    a = (aspect or "9:16").strip()
    if a in ("9:16", "9x16"):
        return 1080, 1920
    return 1920, 1080


def _orient(aspect: str) -> str:
    a = (aspect or "9:16").strip()
    return "portrait" if a in ("9:16", "9x16") else "landscape"


def _fetch_visual(
    query: str,
    prompt: str,
    work: Path,
    *,
    aspect: str,
    idx: int,
) -> tuple[Path | None, str]:
    """Prefer Pexels motion; fall back to Pollinations/Pexels still."""
    try:
        from jarvis.mira.pexels import configured, fetch_videos

        if configured():
            clips, _cred = fetch_videos(
                query or prompt,
                work,
                count=1,
                orientation=_orient(aspect),
                brief=prompt or query,
            )
            if clips:
                return Path(clips[0]), "pexels_video"
    except Exception as exc:
        logger.debug("pexels scene fetch skip: %s", exc)

    try:
        from jarvis.mira.pipeline import generate_still
        from jarvis.mira.quality import enhance_still_prompt

        still_prompt = enhance_still_prompt(prompt or query, style="cinematic")
        w, h = (768, 1280) if _orient(aspect) == "portrait" else (1280, 768)
        img = work / f"still_{idx:02d}_{uuid.uuid4().hex[:6]}.jpg"
        path = generate_still(still_prompt, img, width=w, height=h)
        if path and Path(path).is_file():
            return Path(path), "pollinations_or_still"
    except Exception as exc:
        logger.debug("still scene fetch skip: %s", exc)
    return None, "none"


def compose_legacy_collage(request: VideoGenerationRequest) -> dict[str, Any]:
    """Build a video from planned scenes using stock/still sources + Edge TTS."""
    from jarvis.mira.fast_encode import build_fast_synced_beats
    from jarvis.mira.pipeline import generate_voiceover, out_root
    from jarvis.mira.voices import voice_for_mood

    t0 = time.time()
    notes: list[str] = ["compose=legacy_collage"]
    meta = request.meta or {}
    scenes = list(meta.get("scenes") or [])
    if not scenes:
        return {
            "ok": False,
            "status": "error",
            "message": "No scenes in creative plan — cannot compose.",
            "notes": notes + ["no_scenes"],
        }

    topic = str(meta.get("topic") or request.brief or "scene")[:120]
    aspect = request.aspect or "9:16"
    mood = str(meta.get("tone") or meta.get("mood") or "")
    voice = request.voice or voice_for_mood(mood)
    mode = (request.audio_mode or "voice").strip().lower()
    if mode not in ("voice", "ambient", "both", "mute"):
        mode = "voice"

    root = out_root()
    work = root / "clips" / f"creative_{uuid.uuid4().hex[:10]}"
    work.mkdir(parents=True, exist_ok=True)

    try:
        from jarvis.tools.mira_jobs import set_progress

        set_progress(f"Creative engine: composing {len(scenes)} planned scenes…")
    except Exception:
        pass

    beats: list[dict[str, Any]] = []
    handled: list[str] = []
    narrations: list[str] = []

    for i, sc in enumerate(scenes):
        if not isinstance(sc, dict):
            continue
        sid = str(sc.get("scene_id") or f"s{i+1:02d}")
        query = str(sc.get("search_query") or sc.get("visual_prompt") or topic)[:80]
        prompt = str(sc.get("visual_prompt") or query)[:400]
        narr = str(sc.get("narration") or "").strip()
        role = str(sc.get("role") or "beat")

        vis, src = _fetch_visual(query, prompt, work, aspect=aspect, idx=i)
        if vis is None or not vis.is_file():
            notes.append(f"scene_visual_miss:{sid}")
            continue

        audio_path = None
        if mode in ("voice", "both") and narr:
            try:
                vo_out = work / f"vo_{sid}_{uuid.uuid4().hex[:6]}.mp3"
                audio_path = generate_voiceover(narr, vo_out, voice=voice)
            except Exception as exc:
                notes.append(f"vo_fail:{sid}:{exc}")
                audio_path = None

        beats.append(
            {
                "heading": role.upper()[:24],
                "line": narr or topic,
                "query": query,
                "visual": str(vis),
                "audio": str(audio_path) if audio_path else "",
                "source": src,
                "kind": "motion" if vis.suffix.lower() in (".mp4", ".mov", ".webm") else "still",
                "scene_id": sid,
                "relevance": {"ok": True, "score": 1.0, "matched": [topic.split()[0] if topic else ""]},
            }
        )
        handled.append(sid)
        if narr:
            narrations.append(narr)

    if len(beats) < 1:
        return {
            "ok": False,
            "status": "error",
            "message": (
                "Creative collage could not fetch any on-brief visuals. "
                "Check PEXELS_API_KEY or retry Pollinations."
            )[:280],
            "notes": notes,
            "scenes_handled": handled,
        }

    out_mp4 = root / "videos" / f"vid_creative_{int(time.time())}_{uuid.uuid4().hex[:6]}.mp4"
    try:
        encoded = build_fast_synced_beats(
            beats,
            out_mp4,
            out_size=_out_size(aspect),
            audio_mode=mode,
            fps=30,
            smooth=True,
        )
        out_final = Path(encoded) if encoded else out_mp4
    except Exception as exc:
        return {
            "ok": False,
            "status": "error",
            "message": f"Creative compose encode failed: {exc}"[:240],
            "notes": notes + ["encode_failed"],
            "scenes_handled": handled,
        }
    if not out_final.is_file():
        return {
            "ok": False,
            "status": "error",
            "message": "Creative compose encode failed.",
            "notes": notes + ["encode_failed"],
            "scenes_handled": handled,
        }

    elapsed = time.time() - t0
    return {
        "ok": True,
        "status": "done",
        "video_path": str(out_final),
        "media_url": None,
        "beats": beats,
        "scenes_handled": handled,
        "narrations": narrations,
        "message": (
            f"Creative video ready in {elapsed:.0f}s via legacy stock/still collage "
            f"({len(beats)} scenes) — not neural AI video."
        )[:320],
        "notes": notes,
        "still_source": "legacy_collage",
        "elapsed_sec": round(elapsed, 1),
    }
