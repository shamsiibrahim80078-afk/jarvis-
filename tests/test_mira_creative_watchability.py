"""Phase 5C-1: hook contract, pacing, shot variety, user-script preservation."""

from __future__ import annotations

from jarvis.mira.creative_brief import build_creative_brief, extract_script_lines
from jarvis.mira.scene_planner import (
    build_shot_variety_plans,
    duration_weights_for,
    plan_scenes,
)
from jarvis.mira.generation_provider import VideoGenerationRequest, set_generation_provider


def test_hook_scene_has_distinct_contract():
    brief = build_creative_brief(
        "Make a cinematic story about a detective discovering a secret room",
        duration_sec=30,
    )
    plan = plan_scenes(brief)
    s0 = plan.scenes[0]
    assert (s0.role == "hook") or (s0.story_beat == "hook")
    assert s0.hook_intent
    assert "curios" in s0.hook_intent.lower() or "stakes" in s0.hook_intent.lower() or "media" in s0.hook_intent.lower()
    # Not the old generic establishing language
    low_shot = (s0.shot_plan or "").lower()
    low_vis = (s0.visual_prompt or "").lower()
    assert "wide establishing" not in low_shot
    assert "wide establishing" not in low_vis
    assert "hook" in low_vis
    # Topic appears in hook narration; no empty generic
    assert brief.topic.split()[0].lower() in s0.narration.lower() or any(
        tok in s0.narration.lower() for tok in brief.topic.lower().split() if len(tok) > 4
    )
    assert "HOOK" in s0.continuity_bridge or s0.hook_intent


def test_explainer_hook_is_curiosity_not_suspense():
    brief = build_creative_brief("Make an explainer video about black holes", duration_sec=40)
    plan = plan_scenes(brief)
    s0 = plan.scenes[0]
    assert "curios" in (s0.hook_intent or "").lower()
    assert "suspense" not in (s0.hook_intent or "").lower()
    assert "threat" not in (s0.shot_plan or "").lower()
    assert "?" in s0.narration or "closer look" in s0.narration.lower()


def test_pacing_fast_vs_medium_vs_clear_changes_weights():
    roles = ["hook", "setup", "development", "turn", "payoff"]
    w_fast = duration_weights_for(roles, "fast")
    w_med = duration_weights_for(roles, "medium")
    w_clear = duration_weights_for(roles, "clear")
    assert w_fast[0] > w_med[0]  # stronger early hook
    assert w_fast[1] < w_med[1] or w_fast[2] < w_med[2]  # tighter middle
    # clear gives more to setup / payoff
    assert w_clear[1] > w_med[1]
    assert w_clear[-1] > w_med[-1]

    brief = build_creative_brief(
        "Make a cinematic story about an astronaut on Mars",
        duration_sec=30,
    )
    brief.pacing = "fast"
    plan_f = plan_scenes(brief)
    brief.pacing = "medium"
    plan_m = plan_scenes(brief)
    brief.pacing = "clear"
    plan_c = plan_scenes(brief)

    assert "pacing=fast" in plan_f.notes
    assert "pacing=clear" in plan_c.notes
    # Same total ballpark; hook share higher when fast
    total_f = sum(s.duration_sec for s in plan_f.scenes)
    total_m = sum(s.duration_sec for s in plan_m.scenes)
    assert abs(total_f - brief.duration_sec) < 1.5
    assert abs(total_m - brief.duration_sec) < 1.5
    hook_share_f = plan_f.scenes[0].duration_sec / total_f
    hook_share_m = plan_m.scenes[0].duration_sec / total_m
    assert hook_share_f > hook_share_m
    # clear: setup (index 1 when present) longer than fast's setup
    if len(plan_c.scenes) >= 2 and plan_c.scenes[1].role == "setup":
        assert plan_c.scenes[1].duration_sec >= plan_f.scenes[1].duration_sec
    for s in plan_f.scenes + plan_m.scenes + plan_c.scenes:
        assert 2.0 <= s.duration_sec <= 28.0


def test_adjacent_scenes_have_varied_shot_plans():
    brief = build_creative_brief(
        "Create a suspenseful story about an abandoned house",
        duration_sec=45,
    )
    plan = plan_scenes(brief)
    assert len(plan.scenes) >= 3
    for i in range(1, len(plan.scenes)):
        a = plan.scenes[i - 1].shot_plan
        b = plan.scenes[i].shot_plan
        assert a and b
        assert a != b
        # framing+movement pair should differ
        af, am = [p.strip().lower() for p in a.split(";")[:2]]
        bf, bm = [p.strip().lower() for p in b.split(";")[:2]]
        assert (af, am) != (bf, bm)

    # Continuity language still present
    for sc in plan.scenes[1:]:
        assert "CONTINUATION" in sc.visual_prompt or "Previous scene" in sc.visual_prompt
        assert "prompt-level continuity only" in sc.visual_prompt.lower()

    roles = [s.role for s in plan.scenes]
    plans = build_shot_variety_plans(roles, brief.purpose, brief.topic)
    assert len(plans) == len(roles)


def test_explicit_user_script_lines_preserved():
    ask = (
        "Make a 30 second video about Mars. "
        "Script: First we see the red dust | Then the rover wakes | "
        "Finally Earth calls home"
    )
    lines = extract_script_lines(ask)
    assert len(lines) >= 3
    assert "red dust" in lines[0].lower()
    assert "rover" in lines[1].lower()

    brief = build_creative_brief(ask, duration_sec=30)
    assert brief.script_lines
    assert brief.original_ask
    plan = plan_scenes(brief)
    # First N user lines must appear verbatim (not overwritten by templates)
    for i, line in enumerate(brief.script_lines):
        if i >= len(plan.scenes):
            break
        assert plan.scenes[i].narration == line[:160]
        assert plan.scenes[i].narration_source == "user_script"
    assert "user_script_lines=" in " ".join(plan.notes)


def test_quoted_user_lines_preserved():
    """Quoted lines inside an explicit Script/Narration marker are preserved."""
    ask = (
        'Create a story about a door. Script: "The door opens." '
        '"A light flickers." "Someone steps through."'
    )
    brief = build_creative_brief(ask, duration_sec=30)
    plan = plan_scenes(brief)
    assert any(s.narration_source == "user_script" for s in plan.scenes)
    joined = " ".join(s.narration for s in plan.scenes).lower()
    assert "door opens" in joined
    assert "light flickers" in joined


def test_arbitrary_topics_still_work_without_script():
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
        # Templates fill when no script
        if not brief.script_lines:
            assert all(
                s.narration_source in ("template", "") for s in plan.scenes if s.narration
            )


def test_hf_scene_cap_honesty_still_intact(monkeypatch):
    """Phase 5A regression: plan > cap → submit prefix + deferral metadata."""
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
    finally:
        set_generation_provider(None)


# --- Phase 5C-2 edge-case hardening ---


def test_topic_strips_duration_and_video_chrome():
    brief = build_creative_brief("Make a 30 second video about Mars", duration_sec=30)
    assert brief.topic.strip().lower() == "mars"
    assert "30" not in brief.topic
    assert "second" not in brief.topic.lower()
    assert "video" not in brief.topic.lower()
    assert brief.duration_sec == 30
    assert "mars" in brief.original_ask.lower()


def test_clear_night_skies_not_false_pacing():
    brief = build_creative_brief("Make a video about clear night skies", duration_sec=30)
    assert "clear night skies" in brief.topic.lower()
    # Ordinary topic adjective must not force clear pacing
    assert brief.pacing != "clear"
    assert brief.purpose != "explainer"
    # Explicit instruction still works
    brief2 = build_creative_brief(
        "Make a video about Mars with clear pacing",
        duration_sec=30,
    )
    assert brief2.pacing == "clear"
    assert brief2.topic.strip().lower() == "mars"


def test_quoted_topic_is_not_false_script():
    ask = "Make a funny video about 'office workers' dancing"
    brief = build_creative_brief(ask, duration_sec=30)
    assert not brief.script_lines
    assert "office" in brief.topic.lower()
    plan = plan_scenes(brief)
    assert all(s.narration_source != "user_script" for s in plan.scenes if s.narration)
    # Narration is template comedy, not just the quoted noun
    assert plan.scenes[0].narration_source == "template"
    assert "office" in plan.scenes[0].narration.lower() or "worker" in " ".join(
        s.narration.lower() for s in plan.scenes
    )


def test_explainer_shots_avoid_stakes_language():
    brief = build_creative_brief("Make an explainer video about black holes", duration_sec=40)
    assert brief.purpose == "explainer"
    plan = plan_scenes(brief)
    for sc in plan.scenes:
        low = (sc.shot_plan or "").lower()
        assert "stakes" not in low
        assert "threat" not in low
    # Suspense may still use stronger language
    sus = build_creative_brief(
        "Create a suspenseful story about an abandoned house",
        duration_sec=30,
    )
    plan_s = plan_scenes(sus)
    blob = " ".join((s.shot_plan or "").lower() for s in plan_s.scenes)
    assert "stakes" in blob or "threat" in blob or "partial reveal" in blob


def test_explicit_script_still_preserved_after_5c2():
    ask = (
        "Make a 30 second video about Mars. "
        "Script: First we see the red dust | Then the rover wakes | "
        "Finally Earth calls home"
    )
    brief = build_creative_brief(ask, duration_sec=30)
    assert brief.topic.strip().lower() == "mars"
    assert len(brief.script_lines) >= 3
    plan = plan_scenes(brief)
    assert plan.scenes[0].narration == brief.script_lines[0][:160]
    assert plan.scenes[0].narration_source == "user_script"
