"""Mira creative video engine — brief → story plan → provider → quality.

Phase 5A: coherent story beats + prompt-level continuity; honest HF scene-cap.
Separate from live screen-recording. Router remains the boundary.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from jarvis.mira.creative_brief import build_creative_brief
from jarvis.mira.creative_quality import validate_creative_output
from jarvis.mira.generation_provider import (
    VideoGenerationRequest,
    creative_visual_mode,
    get_generation_provider,
    get_neural_video_provider,
)
from jarvis.mira.scene_planner import plan_scenes

logger = logging.getLogger(__name__)


def _hf_t2v_scene_cap() -> int:
    """Mirror HF provider cost cap without importing/changing that module."""
    try:
        return max(1, min(8, int(os.getenv("MIRA_HF_T2V_MAX_SCENES") or "4")))
    except ValueError:
        return 4


def run_creative_video(
    topic: str,
    *,
    script: str | None = None,
    duration_sec: int = 30,
    aspect: str = "9:16",
    voice: str | None = None,
    audio_mode: str = "voice",
    search_hints: list[str] | None = None,
    mood: str | None = None,
) -> dict[str, Any]:
    """Execute the creative_generative pipeline (not live product tours)."""
    ask = (script or topic or "").strip() or (topic or "").strip()
    if not ask:
        return {"ok": False, "status": "error", "message": "topic is required"}

    try:
        from jarvis.tools.mira_jobs import set_progress

        set_progress("Creative engine: building brief and scene plan…")
    except Exception:
        pass

    brief = build_creative_brief(
        ask,
        duration_sec=duration_sec,
        aspect=aspect,
        search_hints=search_hints,
        audio_mode=audio_mode,
    )
    if mood:
        brief.tone = str(mood)
        brief.extras["mood_override"] = mood

    plan = plan_scenes(brief)
    notes = [
        "creative_engine=phase5a",
        f"purpose={brief.purpose}",
        f"structure={plan.structure}",
        f"visual_mode={creative_visual_mode()}",
        f"scenes_planned={len(plan.scenes)}",
    ]

    provider = get_generation_provider()
    neural = get_neural_video_provider()
    notes.append(f"provider={provider.provider_id}")
    notes.append(f"neural_available={neural.is_available()}")

    full_scenes = [s.to_dict() for s in plan.scenes]
    scenes_for_generation = list(full_scenes)
    deferred_ids: list[str] = []
    cap_applied = False

    # Align generation with HF cost/safety cap — do not silently claim all scenes ran.
    if provider.provider_id == "mira_hf_remote_t2v":
        cap = _hf_t2v_scene_cap()
        notes.append(f"hf_t2v_max_scenes={cap}")
        if len(full_scenes) > cap:
            scenes_for_generation = full_scenes[:cap]
            deferred_ids = [str(s.get("scene_id")) for s in full_scenes[cap:]]
            cap_applied = True
            notes.append(f"scenes_submitted={len(scenes_for_generation)}")
            notes.append(f"scenes_deferred_by_cap={deferred_ids}")

    expected_ids = [str(s.get("scene_id")) for s in scenes_for_generation if s.get("scene_id")]

    req = VideoGenerationRequest(
        brief=brief.topic,
        pipeline="creative_generative",
        duration_sec=brief.duration_sec,
        aspect=brief.aspect,
        voice=voice,
        audio_mode=audio_mode,
        search_hints=list(brief.search_hints),
        meta={
            "topic": brief.topic,
            "tone": brief.tone,
            "mood": brief.tone,
            "visual_style": brief.visual_style,
            "purpose": brief.purpose,
            "continuity": brief.continuity,
            "continuity_mode": "prompt_level_only",
            "original_ask": brief.original_ask,
            "creative_brief": brief.to_dict(),
            "scene_plan": plan.to_dict(),
            "scenes": scenes_for_generation,
            "scenes_planned_full": full_scenes,
            "scenes_deferred_by_cap": deferred_ids,
            "scenes_expected_for_generation": expected_ids,
            "hf_scene_cap_applied": cap_applied,
        },
    )

    try:
        from jarvis.tools.mira_jobs import set_progress

        set_progress(f"Creative engine: generating via {provider.provider_id}…")
    except Exception:
        pass

    raw = provider.generate(req)
    result = dict(raw or {})
    result.setdefault("notes", [])
    result["notes"] = list(result.get("notes") or []) + notes
    result["video_pipeline"] = "creative_generative"
    result["creative_brief"] = brief.to_dict()
    result["scene_plan"] = plan.to_dict()
    result["scenes_planned_count"] = len(full_scenes)
    result["scenes_submitted_count"] = len(scenes_for_generation)
    result["scenes_deferred_by_cap"] = deferred_ids
    result["scenes_expected_for_generation"] = expected_ids
    result.setdefault("scenes_handled", result.get("scenes_handled") or [])

    if cap_applied:
        msg_cap = (
            f"Story planned {len(full_scenes)} scenes; HF generation cap "
            f"submitted {len(scenes_for_generation)} "
            f"(deferred: {', '.join(deferred_ids)}). "
            "Prompt-level continuity only."
        )
        result["scene_cap_note"] = msg_cap
        result["notes"].append("honesty=scene_cap_partial_generation")

    if not result.get("ok"):
        result["status"] = result.get("status") or "error"
        return result

    if cap_applied and result.get("ok"):
        base_msg = (result.get("message") or "Video ready.").rstrip()
        if "cap" not in base_msg.lower() and "deferred" not in base_msg.lower():
            result["message"] = f"{base_msg} ({result.get('scene_cap_note')})"[:360]

    narrations = list(
        result.get("narrations")
        or [s.narration for s in plan.scenes if s.narration]
    )
    # Quality expects only scenes that were actually submitted for generation
    quality = validate_creative_output(
        result,
        expected_aspect=brief.aspect,
        expected_duration_sec=brief.duration_sec,
        planned_scene_ids=expected_ids,
        narrations=narrations,
    )
    result["creative_quality"] = quality
    result["notes"].append(f"quality={quality.get('message')}")
    if not quality.get("ok"):
        issues = quality.get("issues") or []
        hard = {"missing_file", "file_too_small", "generate_failed", "false_neural_claim"}
        if hard.intersection(issues):
            result["ok"] = False
            result["status"] = "error"
            result["message"] = (
                f"Creative output failed quality checks: {', '.join(issues[:5])}"
            )[:280]
    return result
