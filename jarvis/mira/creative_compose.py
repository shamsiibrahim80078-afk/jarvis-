"""Compose creative scene plans into a video using existing Mira encoders.

Legacy collage: Pexels clips / Pollinations stills + Edge TTS + fast_encode.
Remote neural: pre-generated HF T2V scene MP4s + Edge TTS + fast_encode.
Phase 5B: planned scene timing + optional narration captions.
Legacy results are never labeled as neural AI video.
"""

from __future__ import annotations

import logging
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


def _want_captions(request: VideoGenerationRequest) -> bool:
    meta = request.meta or {}
    brief = meta.get("creative_brief")
    if isinstance(brief, dict) and brief.get("captions"):
        return True
    if meta.get("captions"):
        return True
    return False


def _scene_planned_duration(sc: dict[str, Any], *, fallback: float = 3.0) -> float:
    try:
        d = float(sc.get("duration_sec") or 0)
    except (TypeError, ValueError):
        d = 0.0
    if d >= 1.0:
        return round(min(28.0, max(1.5, d)), 2)
    return fallback


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


def _compose_beats_to_mp4(
    request: VideoGenerationRequest,
    beats: list[dict[str, Any]],
    *,
    notes: list[str],
    handled: list[str],
    narrations: list[str],
    t0: float,
    source_label: str,
    is_neural_video: bool,
    generation_kind: str,
    provider_id: str | None = None,
    success_message: str | None = None,
) -> dict[str, Any]:
    """Shared fast_encode path for legacy collage and neural scene clips."""
    from jarvis.mira.fast_encode import _probe_duration, build_fast_synced_beats
    from jarvis.mira.pipeline import out_root

    aspect = request.aspect or "9:16"
    mode = (request.audio_mode or "voice").strip().lower()
    if mode not in ("voice", "ambient", "both", "mute"):
        mode = "voice"

    root = out_root()
    out_mp4 = root / "videos" / f"vid_creative_{int(time.time())}_{uuid.uuid4().hex[:6]}.mp4"
    planned_total = sum(float(b.get("duration_sec") or 0) for b in beats if isinstance(b, dict))
    encode_status: dict[str, Any] = {}
    try:
        encoded = build_fast_synced_beats(
            beats,
            out_mp4,
            out_size=_out_size(aspect),
            audio_mode=mode,
            fps=30,
            smooth=True,
            status_out=encode_status,
        )
        out_final = Path(encoded) if encoded else out_mp4
    except Exception as exc:
        return {
            "ok": False,
            "status": "error",
            "message": f"Creative compose encode failed: {exc}"[:240],
            "notes": notes + ["encode_failed"],
            "scenes_handled": handled,
            "provider": provider_id,
            "generation_kind": generation_kind,
            "is_neural_video": False,
        }
    if not out_final.is_file():
        return {
            "ok": False,
            "status": "error",
            "message": "Creative compose encode failed.",
            "notes": notes + ["encode_failed"],
            "scenes_handled": handled,
            "provider": provider_id,
            "generation_kind": generation_kind,
            "is_neural_video": False,
        }

    elapsed = time.time() - t0
    actual_dur = 0.0
    try:
        actual_dur = float(_probe_duration(out_final) or 0.0)
    except Exception:
        actual_dur = 0.0
    if success_message:
        try:
            msg = success_message.format(elapsed=elapsed, n_beats=len(beats))
        except Exception:
            msg = success_message
    else:
        msg = (
            f"Creative video ready in {elapsed:.0f}s via {source_label} "
            f"({len(beats)} scenes)."
        )
    out: dict[str, Any] = {
        "ok": True,
        "status": "done",
        "video_path": str(out_final),
        "media_url": None,
        "beats": beats,
        "scenes_handled": handled,
        "narrations": narrations,
        "message": msg[:320],
        "notes": list(notes),
        "still_source": source_label,
        "elapsed_sec": round(elapsed, 1),
        "generation_kind": generation_kind,
        "is_neural_video": bool(is_neural_video),
        "planned_duration_sec": round(planned_total, 2) if planned_total > 0 else None,
        "actual_duration_sec": round(actual_dur, 2) if actual_dur > 0 else None,
        "requested_duration_sec": int(request.duration_sec or 0) or None,
    }
    cap_status = str(encode_status.get("captions") or "")
    if encode_status.get("captions_requested"):
        out["captions_requested"] = True
        if encode_status.get("captions_burn_failed") or cap_status == "requested_but_unavailable":
            out["captions_burn_failed"] = True
            out["captions_status"] = "requested_but_unavailable"
            # Replace false "captions=on" success signal
            out["notes"] = [
                n for n in out["notes"] if n not in ("captions=on",)
            ]
            out["notes"].append("captions=requested_but_unavailable")
            out["notes"].append("captions_burn_failed=true")
        else:
            out["captions_burn_failed"] = False
            out["captions_status"] = "burned"
    else:
        out["captions_requested"] = False
        out["captions_burn_failed"] = False
        out["captions_status"] = cap_status or "off"
    if provider_id:
        out["provider"] = provider_id
    return out


def _build_scene_beat(
    *,
    sid: str,
    vis: Path,
    narr: str,
    query: str,
    role: str,
    topic: str,
    source: str,
    planned_dur: float,
    captions: bool,
) -> dict[str, Any]:
    beat: dict[str, Any] = {
        "heading": "",  # role titles not burned; captions use narration when enabled
        "line": narr or topic,
        "query": query,
        "visual": str(vis),
        "audio": "",
        "source": source,
        "kind": "motion" if vis.suffix.lower() in (".mp4", ".mov", ".webm") else "still",
        "scene_id": sid,
        "duration_sec": planned_dur,
        "planned_duration_sec": planned_dur,
        "relevance": {
            "ok": True,
            "score": 1.0,
            "matched": [topic.split()[0] if topic else ""],
        },
    }
    if captions and narr:
        beat["caption"] = narr[:120]
    return beat


def compose_from_visual_paths(
    request: VideoGenerationRequest,
    scenes: list[dict[str, Any]],
    *,
    source_label: str = "scene_clips",
    is_neural_video: bool = False,
    generation_kind: str = "remote_t2v",
    provider_id: str | None = None,
) -> dict[str, Any]:
    """Compose pre-generated scene visuals (e.g. remote T2V MP4s) + Edge TTS."""
    from jarvis.mira.pipeline import generate_voiceover, out_root
    from jarvis.mira.voices import voice_for_mood

    t0 = time.time()
    notes: list[str] = [f"compose={source_label}", "timing=planned_duration"]
    if not scenes:
        return {
            "ok": False,
            "status": "error",
            "message": "No scene visuals to compose.",
            "notes": notes + ["no_scenes"],
            "generation_kind": generation_kind,
            "is_neural_video": False,
            "provider": provider_id,
        }

    meta = request.meta or {}
    topic = str(meta.get("topic") or request.brief or "scene")[:120]
    mood = str(meta.get("tone") or meta.get("mood") or "")
    voice = request.voice or voice_for_mood(mood)
    mode = (request.audio_mode or "voice").strip().lower()
    if mode not in ("voice", "ambient", "both", "mute"):
        mode = "voice"
    captions = _want_captions(request)
    notes.append(f"captions={'on' if captions else 'off'}")

    root = out_root()
    work = root / "clips" / f"compose_{uuid.uuid4().hex[:10]}"
    work.mkdir(parents=True, exist_ok=True)

    try:
        from jarvis.tools.mira_jobs import set_progress

        set_progress(f"Creative engine: composing {len(scenes)} scene clips…")
    except Exception:
        pass

    # Preserve story order; do not reshuffle
    ordered = [sc for sc in scenes if isinstance(sc, dict)]
    beats: list[dict[str, Any]] = []
    handled: list[str] = []
    narrations: list[str] = []

    for i, sc in enumerate(ordered):
        sid = str(sc.get("scene_id") or f"s{i+1:02d}")
        vis_raw = sc.get("visual_path") or sc.get("neural_clip") or ""
        vis = Path(str(vis_raw)) if vis_raw else None
        if vis is None or not vis.is_file():
            notes.append(f"scene_visual_miss:{sid}")
            continue
        query = str(sc.get("search_query") or sc.get("visual_prompt") or topic)[:80]
        narr = str(sc.get("narration") or "").strip()
        role = str(sc.get("role") or sc.get("story_beat") or "beat")
        planned = _scene_planned_duration(sc)

        audio_path = None
        if mode in ("voice", "both") and narr:
            try:
                vo_out = work / f"vo_{sid}_{uuid.uuid4().hex[:6]}.mp3"
                audio_path = generate_voiceover(narr, vo_out, voice=voice)
            except Exception as exc:
                notes.append(f"vo_fail:{sid}:{exc}")
                audio_path = None

        beat = _build_scene_beat(
            sid=sid,
            vis=vis,
            narr=narr,
            query=query,
            role=role,
            topic=topic,
            source=source_label,
            planned_dur=planned,
            captions=captions,
        )
        beat["audio"] = str(audio_path) if audio_path else ""
        beats.append(beat)
        handled.append(sid)
        if narr:
            narrations.append(narr)

    if len(beats) < 1:
        return {
            "ok": False,
            "status": "error",
            "message": "No usable scene clips to compose.",
            "notes": notes,
            "scenes_handled": handled,
            "generation_kind": generation_kind,
            "is_neural_video": False,
            "provider": provider_id,
        }

    # Honesty: report if any submitted scene lacked a visual (partial assemble)
    submitted_ids = [str(sc.get("scene_id") or "") for sc in ordered if sc.get("scene_id")]
    missed = [s for s in submitted_ids if s and s not in handled]
    if missed:
        notes.append(f"scenes_missing_visual={missed[:4]}")

    kind_label = "remote neural T2V" if is_neural_video else source_label
    return _compose_beats_to_mp4(
        request,
        beats,
        notes=notes,
        handled=handled,
        narrations=narrations,
        t0=t0,
        source_label=source_label,
        is_neural_video=is_neural_video,
        generation_kind=generation_kind,
        provider_id=provider_id,
        success_message=(
            f"Creative video ready in {{elapsed:.0f}}s via {kind_label} "
            f"({{n_beats}} scenes)."
        ),
    )


def compose_legacy_collage(request: VideoGenerationRequest) -> dict[str, Any]:
    """Build a video from planned scenes using stock/still sources + Edge TTS."""
    from jarvis.mira.pipeline import generate_voiceover, out_root
    from jarvis.mira.voices import voice_for_mood

    t0 = time.time()
    notes: list[str] = ["compose=legacy_collage", "timing=planned_duration"]
    meta = request.meta or {}
    scenes = list(meta.get("scenes") or [])
    if not scenes:
        return {
            "ok": False,
            "status": "error",
            "message": "No scenes in creative plan — cannot compose.",
            "notes": notes + ["no_scenes"],
            "generation_kind": "legacy_stock_collage",
            "is_neural_video": False,
        }

    topic = str(meta.get("topic") or request.brief or "scene")[:120]
    aspect = request.aspect or "9:16"
    mood = str(meta.get("tone") or meta.get("mood") or "")
    voice = request.voice or voice_for_mood(mood)
    mode = (request.audio_mode or "voice").strip().lower()
    if mode not in ("voice", "ambient", "both", "mute"):
        mode = "voice"
    captions = _want_captions(request)
    notes.append(f"captions={'on' if captions else 'off'}")

    root = out_root()
    work = root / "clips" / f"creative_{uuid.uuid4().hex[:10]}"
    work.mkdir(parents=True, exist_ok=True)

    try:
        from jarvis.tools.mira_jobs import set_progress

        set_progress(f"Creative engine: composing {len(scenes)} planned scenes…")
    except Exception:
        pass

    ordered = [sc for sc in scenes if isinstance(sc, dict)]
    beats: list[dict[str, Any]] = []
    handled: list[str] = []
    narrations: list[str] = []

    for i, sc in enumerate(ordered):
        sid = str(sc.get("scene_id") or f"s{i+1:02d}")
        query = str(sc.get("search_query") or sc.get("visual_prompt") or topic)[:80]
        prompt = str(sc.get("visual_prompt") or query)[:400]
        narr = str(sc.get("narration") or "").strip()
        role = str(sc.get("role") or sc.get("story_beat") or "beat")
        planned = _scene_planned_duration(sc)

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

        beat = _build_scene_beat(
            sid=sid,
            vis=vis,
            narr=narr,
            query=query,
            role=role,
            topic=topic,
            source=src,
            planned_dur=planned,
            captions=captions,
        )
        beat["audio"] = str(audio_path) if audio_path else ""
        beats.append(beat)
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
            "generation_kind": "legacy_stock_collage",
            "is_neural_video": False,
        }

    return _compose_beats_to_mp4(
        request,
        beats,
        notes=notes,
        handled=handled,
        narrations=narrations,
        t0=t0,
        source_label="legacy_collage",
        is_neural_video=False,
        generation_kind="legacy_stock_collage",
        provider_id="mira_legacy_stock_collage",
        success_message=(
            "Creative video ready in {elapsed:.0f}s via legacy stock/still collage "
            "({n_beats} scenes) — not neural AI video."
        ),
    )
