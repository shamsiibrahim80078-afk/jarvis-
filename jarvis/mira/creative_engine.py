"""Mira Phase 2 creative video engine — brief → plan → provider → quality.

Separate from live screen-recording. Router remains the boundary.
"""

from __future__ import annotations

import logging
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
        "creative_engine=phase4",
        f"purpose={brief.purpose}",
        f"structure={plan.structure}",
        f"visual_mode={creative_visual_mode()}",
    ]

    provider = get_generation_provider()
    neural = get_neural_video_provider()
    notes.append(f"provider={provider.provider_id}")
    notes.append(f"neural_available={neural.is_available()}")

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
            "original_ask": brief.original_ask,
            "creative_brief": brief.to_dict(),
            "scene_plan": plan.to_dict(),
            "scenes": [s.to_dict() for s in plan.scenes],
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
    result.setdefault("scenes_handled", result.get("scenes_handled") or [])

    if not result.get("ok"):
        result["status"] = result.get("status") or "error"
        return result

    narrations = list(result.get("narrations") or [s.narration for s in plan.scenes if s.narration])
    quality = validate_creative_output(
        result,
        expected_aspect=brief.aspect,
        expected_duration_sec=brief.duration_sec,
        planned_scene_ids=[s.scene_id for s in plan.scenes],
        narrations=narrations,
    )
    result["creative_quality"] = quality
    result["notes"].append(f"quality={quality.get('message')}")
    if not quality.get("ok"):
        # Soft-fail quality: keep file if present but surface issues
        issues = quality.get("issues") or []
        hard = {"missing_file", "file_too_small", "generate_failed", "false_neural_claim"}
        if hard.intersection(issues):
            result["ok"] = False
            result["status"] = "error"
            result["message"] = (
                f"Creative output failed quality checks: {', '.join(issues[:5])}"
            )[:280]
    return result
