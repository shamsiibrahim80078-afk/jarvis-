"""Phase 2/5A: creative brief, story planner, provider honesty, routing regression."""

from __future__ import annotations

import os

from jarvis.mira.creative_brief import build_creative_brief
from jarvis.mira.generation_provider import (
    LegacyStockCollageProvider,
    UnavailableNeuralVideoProvider,
    VideoGenerationRequest,
    creative_visual_mode,
    get_generation_provider,
    get_neural_video_provider,
    set_generation_provider,
)
from jarvis.mira.scene_planner import plan_scenes
from jarvis.mira.video_router import requires_live_hard_lock, route_video_ask
from jarvis.tools.mira_tool import parse_mira_command


def test_creative_brief_infers_without_hardcoded_topics():
    brief = build_creative_brief(
        "Make a cinematic 30 second video about an astronaut finding something strange on Mars",
        duration_sec=30,
        aspect="9:16",
    )
    assert "astronaut" in brief.topic.lower() or "mars" in brief.topic.lower()
    assert brief.duration_sec == 30
    assert brief.aspect == "9:16"
    assert brief.purpose in ("story", "suspense", "general")
    assert brief.scene_count >= 3
    assert brief.narration is True


def test_explainer_brief_and_structure():
    brief = build_creative_brief("Make an explainer video about black holes", duration_sec=40)
    assert brief.purpose == "explainer"
    plan = plan_scenes(brief)
    roles = [s.role for s in plan.scenes]
    assert "hook" in roles
    assert any(r in roles for r in ("information", "explanation", "conclusion"))
    assert "HOOK" in plan.structure.upper()


def test_scene_plan_has_required_fields_and_unique_narration():
    brief = build_creative_brief(
        "Create a suspenseful YouTube Short about an abandoned house",
        duration_sec=30,
        aspect="9:16",
    )
    plan = plan_scenes(brief)
    assert len(plan.scenes) >= 3
    narrs = []
    for s in plan.scenes:
        assert s.scene_id
        assert s.duration_sec > 0
        assert s.visual_prompt
        assert s.search_query
        assert s.narration
        narrs.append(s.narration.lower())
    # Not all identical (coherent sequence, not one repeated line)
    assert len(set(narrs)) >= 2


def test_story_beat_assignment_adapts_to_scene_count():
    brief = build_creative_brief(
        "Make a cinematic story about a detective discovering a secret room",
        duration_sec=30,
    )
    assert brief.purpose == "story"
    plan = plan_scenes(brief)
    beats = [s.story_beat or s.role for s in plan.scenes]
    assert beats[0] == "hook"
    assert beats[-1] == "payoff"
    assert any(b in beats for b in ("setup", "development", "turn", "escalation"))
    assert " → ".join(b.upper() for b in beats) == plan.structure

    brief6 = build_creative_brief(
        "Make a 60 second cinematic story about an astronaut on Mars",
        duration_sec=60,
    )
    plan6 = plan_scenes(brief6)
    assert len(plan6.scenes) >= 5
    assert (plan6.scenes[0].story_beat or plan6.scenes[0].role) == "hook"
    assert (plan6.scenes[-1].story_beat or plan6.scenes[-1].role) == "payoff"


def test_scene_continuity_context_between_scenes():
    brief = build_creative_brief(
        "Create a suspenseful story about an abandoned house",
        duration_sec=30,
    )
    plan = plan_scenes(brief)
    assert plan.scenes[0].previous_scene_summary == ""
    for i, sc in enumerate(plan.scenes):
        assert sc.continuity
        assert sc.continuity_bridge
        assert sc.progress_note
        low = sc.visual_prompt.lower()
        assert "subject" in low or "continu" in low
        if i > 0:
            assert sc.previous_scene_summary
            assert "CONTINUATION" in sc.visual_prompt or "Previous scene" in sc.visual_prompt
            prev = plan.scenes[i - 1]
            assert (prev.role in sc.continuity_bridge) or (
                (prev.story_beat or "") in sc.continuity_bridge
            )


def test_sequence_aware_narration_advances_story():
    brief = build_creative_brief(
        "Make a cinematic detective story about a secret room",
        duration_sec=45,
    )
    plan = plan_scenes(brief)
    narrs = [s.narration.strip().lower() for s in plan.scenes if s.narration.strip()]
    assert len(narrs) >= 3
    assert len(set(narrs)) == len(narrs)
    topic = brief.topic.strip().lower()
    assert not all(n == topic or n == f"{topic}." for n in narrs)


def test_arbitrary_topics_not_hardcoded():
    for ask in (
        "funny 30-second video about office workers",
        "realistic 9:16 video about a futuristic city",
        "cinematic detective discovering a secret room",
    ):
        brief = build_creative_brief(ask)
        plan = plan_scenes(brief)
        assert plan.scenes
        blob = " ".join(s.visual_prompt.lower() for s in plan.scenes)
        assert any(tok in blob for tok in ask.lower().split() if len(tok) > 4)


def test_hf_scene_cap_reported_honestly(monkeypatch):
    """When plan > MIRA_HF_T2V_MAX_SCENES, engine submits a prefix and reports deferrals."""
    from jarvis.mira import creative_engine as eng

    monkeypatch.setenv("MIRA_HF_T2V_MAX_SCENES", "2")

    class _FakeHF:
        provider_id = "mira_hf_remote_t2v"

        def is_available(self) -> bool:
            return True

        def generate(self, request: VideoGenerationRequest) -> dict:
            scenes = list((request.meta or {}).get("scenes") or [])
            assert len(scenes) == 2
            return {
                "ok": True,
                "status": "done",
                "video_path": "",
                "message": "fake ok",
                "scenes_handled": [s["scene_id"] for s in scenes],
                "narrations": [s.get("narration") or "" for s in scenes],
                "notes": [],
                "provider": self.provider_id,
                "generation_kind": "remote_t2v",
                "is_neural_video": False,
            }

    set_generation_provider(_FakeHF())
    try:
        out = eng.run_creative_video(
            "Make a 60 second cinematic story about an astronaut on Mars",
            duration_sec=60,
        )
        assert out.get("scenes_planned_count", 0) > 2
        assert out.get("scenes_submitted_count") == 2
        assert out.get("scenes_deferred_by_cap")
        assert out.get("scene_cap_note")
        assert "honesty=scene_cap_partial_generation" in (out.get("notes") or [])
        expected = out.get("scenes_expected_for_generation") or []
        assert len(expected) == 2
    finally:
        set_generation_provider(None)


def test_product_still_live_creative_does_not():
    live = route_video_ask("record a demo of Gemini")
    assert live.pipeline == "live_screen"
    assert requires_live_hard_lock(live)

    creative = route_video_ask("Make a cinematic detective story")
    assert creative.pipeline == "creative_generative"
    assert not requires_live_hard_lock(creative)

    parsed = parse_mira_command("create a video of cryptorafts")
    assert parsed and parsed.get("platform_tour") is True
    parsed2 = parse_mira_command("make a cinematic video about a detective")
    assert parsed2 and parsed2.get("platform_tour") is False
    assert parsed2.get("video_pipeline") == "creative_generative"


def test_neural_provider_unavailable_honest():
    # Clear token for this test so neural stays unavailable
    old = os.environ.get("HF_TOKEN")
    os.environ.pop("HF_TOKEN", None)
    set_generation_provider(None)
    try:
        p = get_neural_video_provider()
        assert isinstance(p, UnavailableNeuralVideoProvider)
        assert p.is_available() is False
        out = p.generate(VideoGenerationRequest(brief="astronaut on mars"))
        assert out["ok"] is False
        assert out["status"] == "unavailable"
        assert out.get("is_neural_video") is False
        assert not out.get("video_path")
    finally:
        if old is None:
            os.environ.pop("HF_TOKEN", None)
        else:
            os.environ["HF_TOKEN"] = old
        set_generation_provider(None)


def test_neural_only_mode_does_not_pretend_success():
    old = os.environ.get("MIRA_CREATIVE_VISUAL_MODE")
    old_tok = os.environ.get("HF_TOKEN")
    os.environ["MIRA_CREATIVE_VISUAL_MODE"] = "neural_only"
    os.environ.pop("HF_TOKEN", None)
    set_generation_provider(None)
    try:
        assert creative_visual_mode() == "neural_only"
        p = get_generation_provider()
        assert p.is_available() is False
        out = p.generate(VideoGenerationRequest(brief="futuristic city"))
        assert out["ok"] is False
        assert out.get("generation_kind") == "neural_video"
        assert not out.get("video_path")
    finally:
        if old is None:
            os.environ.pop("MIRA_CREATIVE_VISUAL_MODE", None)
        else:
            os.environ["MIRA_CREATIVE_VISUAL_MODE"] = old
        if old_tok is None:
            os.environ.pop("HF_TOKEN", None)
        else:
            os.environ["HF_TOKEN"] = old_tok
        set_generation_provider(None)


def test_legacy_provider_is_explicitly_labeled():
    p = LegacyStockCollageProvider()
    assert p.provider_id == "mira_legacy_stock_collage"
    assert "legacy" in p.provider_id


def test_mira_jobs_progress_helpers_still_import():
    from jarvis.tools.mira_jobs import get_status, set_progress

    assert callable(get_status)
    assert callable(set_progress)
    st = get_status()
    assert isinstance(st, dict)
    assert "status" in st
