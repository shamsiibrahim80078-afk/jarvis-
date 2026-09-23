"""Phase 5B: planned timing, captions, multi-scene assembly, duration honesty."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from jarvis.mira.creative_brief import build_creative_brief
from jarvis.mira.creative_compose import (
    _build_scene_beat,
    _scene_planned_duration,
    _want_captions,
    compose_from_visual_paths,
)
from jarvis.mira.creative_quality import validate_creative_output
from jarvis.mira.fast_encode import resolve_segment_take
from jarvis.mira.generation_provider import VideoGenerationRequest, set_generation_provider
from jarvis.mira.scene_planner import plan_scenes


def test_resolve_segment_take_uses_planned_duration():
    take, stretch = resolve_segment_take(
        planned_duration=7.5,
        src_dur=10.0,
        vo_dur=2.0,
        is_image=False,
        audio_mode="voice",
    )
    assert abs(take - 7.5) < 0.01
    assert stretch <= 1.01


def test_resolve_segment_take_extends_for_long_vo_without_speeding_speech():
    take, stretch = resolve_segment_take(
        planned_duration=4.0,
        src_dur=12.0,
        vo_dur=6.0,
        is_image=False,
        audio_mode="voice",
    )
    assert take >= 6.0
    assert stretch <= 1.01


def test_resolve_segment_take_mild_stretch_when_clip_short():
    take, stretch = resolve_segment_take(
        planned_duration=8.0,
        src_dur=4.0,
        vo_dur=0.0,
        is_image=False,
        audio_mode="mute",
    )
    assert abs(take - 8.0) < 0.01
    assert 1.05 < stretch <= 1.35


def test_legacy_heuristic_without_plan_still_works():
    take, stretch = resolve_segment_take(
        planned_duration=None,
        src_dur=5.0,
        vo_dur=3.0,
        is_image=False,
        audio_mode="voice",
        smooth=True,
    )
    assert take >= 3.0
    assert stretch >= 1.0


def test_scene_planned_duration_propagation():
    assert _scene_planned_duration({"duration_sec": 5.5}) == 5.5
    assert _scene_planned_duration({"duration_sec": 0.2}, fallback=3.0) == 3.0


def test_want_captions_from_brief_meta():
    req_on = VideoGenerationRequest(
        brief="x",
        meta={"creative_brief": {"captions": True}},
    )
    req_off = VideoGenerationRequest(
        brief="x",
        meta={"creative_brief": {"captions": False}},
    )
    assert _want_captions(req_on) is True
    assert _want_captions(req_off) is False


def test_build_scene_beat_captions_on_off(tmp_path: Path):
    vis = tmp_path / "c.mp4"
    vis.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 100)
    on = _build_scene_beat(
        sid="s01",
        vis=vis,
        narr="It opens on the house.",
        query="house",
        role="hook",
        topic="abandoned house",
        source="test",
        planned_dur=5.0,
        captions=True,
    )
    off = _build_scene_beat(
        sid="s01",
        vis=vis,
        narr="It opens on the house.",
        query="house",
        role="hook",
        topic="abandoned house",
        source="test",
        planned_dur=5.0,
        captions=False,
    )
    assert on.get("caption") == "It opens on the house."
    assert on.get("duration_sec") == 5.0
    assert "caption" not in off
    assert off.get("heading") == ""


def test_compose_preserves_story_order_and_planned_timing(tmp_path: Path):
    clips = tmp_path / "clips"
    clips.mkdir()
    paths = []
    for i in range(3):
        p = clips / f"s{i+1:02d}.mp4"
        p.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 12_000)
        paths.append(p)

    scenes = [
        {
            "scene_id": "s01",
            "duration_sec": 4.0,
            "narration": "Line one.",
            "role": "hook",
            "visual_path": str(paths[0]),
            "search_query": "a",
        },
        {
            "scene_id": "s02",
            "duration_sec": 5.0,
            "narration": "Line two.",
            "role": "setup",
            "visual_path": str(paths[1]),
            "search_query": "b",
        },
        {
            "scene_id": "s03",
            "duration_sec": 6.0,
            "narration": "Line three.",
            "role": "payoff",
            "visual_path": str(paths[2]),
            "search_query": "c",
        },
    ]
    req = VideoGenerationRequest(
        brief="story",
        duration_sec=15,
        audio_mode="mute",
        meta={
            "topic": "story",
            "creative_brief": {"captions": True},
            "scenes": scenes,
        },
    )

    captured: dict = {}

    def _fake_encode(beats, out_mp4, **kwargs):
        captured["beats"] = list(beats)
        out = Path(out_mp4)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 30_000)
        return out

    with patch("jarvis.mira.creative_compose.out_root", create=True), patch(
        "jarvis.mira.pipeline.out_root", return_value=tmp_path / "out"
    ), patch(
        "jarvis.mira.fast_encode.build_fast_synced_beats", side_effect=_fake_encode
    ), patch(
        "jarvis.mira.fast_encode._probe_duration", return_value=15.0
    ):
        (tmp_path / "out" / "videos").mkdir(parents=True, exist_ok=True)
        out = compose_from_visual_paths(
            req,
            scenes,
            source_label="test",
            is_neural_video=False,
            generation_kind="legacy_stock_collage",
            provider_id="test",
        )

    assert out.get("ok") is True
    assert out.get("scenes_handled") == ["s01", "s02", "s03"]
    beats = captured["beats"]
    assert [b["scene_id"] for b in beats] == ["s01", "s02", "s03"]
    assert [b["duration_sec"] for b in beats] == [4.0, 5.0, 6.0]
    assert all(b.get("caption") for b in beats)
    assert "timing=planned_duration" in (out.get("notes") or [])
    assert "captions=on" in (out.get("notes") or [])


def test_compose_captions_disabled_omits_caption_field(tmp_path: Path):
    p = tmp_path / "s01.mp4"
    p.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 12_000)
    scenes = [
        {
            "scene_id": "s01",
            "duration_sec": 4.0,
            "narration": "Hello world.",
            "role": "hook",
            "visual_path": str(p),
            "search_query": "x",
        }
    ]
    req = VideoGenerationRequest(
        brief="x",
        audio_mode="mute",
        meta={"topic": "x", "creative_brief": {"captions": False}, "scenes": scenes},
    )
    captured: dict = {}

    def _fake_encode(beats, out_mp4, **kwargs):
        captured["beats"] = list(beats)
        out = Path(out_mp4)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 30_000)
        return out

    with patch("jarvis.mira.pipeline.out_root", return_value=tmp_path / "out"), patch(
        "jarvis.mira.fast_encode.build_fast_synced_beats", side_effect=_fake_encode
    ), patch(
        "jarvis.mira.fast_encode._probe_duration", return_value=4.0
    ):
        (tmp_path / "out" / "videos").mkdir(parents=True, exist_ok=True)
        out = compose_from_visual_paths(req, scenes, provider_id="test")
    assert out.get("ok") is True
    assert "caption" not in captured["beats"][0]
    assert "captions=off" in (out.get("notes") or [])


def test_duration_validation_tolerance():
    ok = validate_creative_output(
        {
            "ok": True,
            "video_path": __file__,  # exists but may be small — use fake size path carefully
            "scenes_handled": ["s01"],
            "actual_duration_sec": 28.0,
            "planned_duration_sec": 30.0,
        },
        expected_aspect="9:16",
        expected_duration_sec=30,
        planned_scene_ids=["s01"],
        narrations=["a"],
    )
    # __file__ is small → file_too_small likely; focus on duration helpers via probe fail fallback
    # Use a temp large file instead in a tighter test below
    assert isinstance(ok.get("issues"), list)


def test_duration_validation_with_large_temp_file(tmp_path: Path):
    vid = tmp_path / "out.mp4"
    vid.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 40_000)
    with patch("jarvis.mira.creative_quality._probe_duration", return_value=29.0), patch(
        "jarvis.mira.creative_quality._probe_wh", return_value=(1080, 1920)
    ):
        q = validate_creative_output(
            {
                "ok": True,
                "video_path": str(vid),
                "scenes_handled": ["s01", "s02"],
                "scenes_expected_for_generation": ["s01", "s02"],
                "actual_duration_sec": 29.0,
                "planned_duration_sec": 30.0,
                "is_neural_video": False,
                "generation_kind": "legacy_stock_collage",
            },
            expected_aspect="9:16",
            expected_duration_sec=30,
            planned_scene_ids=["s01", "s02"],
            narrations=["one", "two"],
        )
    assert q.get("ok") is True
    assert "duration_far_from_request" not in (q.get("issues") or [])


def test_scenes_out_of_order_detected(tmp_path: Path):
    vid = tmp_path / "out.mp4"
    vid.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 40_000)
    with patch("jarvis.mira.creative_quality._probe_duration", return_value=20.0), patch(
        "jarvis.mira.creative_quality._probe_wh", return_value=(1080, 1920)
    ):
        q = validate_creative_output(
            {
                "ok": True,
                "video_path": str(vid),
                "scenes_handled": ["s02", "s01"],
                "scenes_expected_for_generation": ["s01", "s02"],
                "generation_kind": "legacy_stock_collage",
                "is_neural_video": False,
            },
            expected_aspect="9:16",
            expected_duration_sec=20,
            planned_scene_ids=["s01", "s02"],
            narrations=["a", "b"],
        )
    assert "scenes_out_of_order" in (q.get("issues") or [])


def test_planner_durations_flow_into_scene_dicts():
    brief = build_creative_brief(
        "Make a cinematic story about a detective with captions",
        duration_sec=30,
    )
    assert brief.captions is True
    plan = plan_scenes(brief)
    assert all(s.duration_sec >= 2.0 for s in plan.scenes)
    total = sum(s.duration_sec for s in plan.scenes)
    assert abs(total - brief.duration_sec) < 1.5


def test_drawtext_failure_reports_caption_unavailable_keeps_planned_timing(tmp_path: Path):
    """Simulate drawtext failure: fallback succeeds, captions honesty + planned apad/-t."""
    from jarvis.mira import fast_encode as fe

    vis = tmp_path / "clip.mp4"
    vis.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 12_000)
    aud = tmp_path / "vo.mp3"
    aud.write_bytes(b"ID3" + b"\x00" * 2000)
    out_mp4 = tmp_path / "final.mp4"
    calls: list[str] = []

    def fake_run(cmd, timeout=180.0):
        s = " ".join(str(x) for x in cmd)
        calls.append(s)
        if "drawtext=" in s:
            raise RuntimeError("ffmpeg failed: drawtext unavailable")
        target = Path(str(cmd[-1]))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 8_000)

    status: dict = {}
    with patch.object(fe, "_run", side_effect=fake_run), patch.object(
        fe, "_probe_duration", return_value=5.0
    ), patch.object(fe, "_audio_duration", return_value=2.0), patch.object(
        fe, "_ffmpeg", return_value="ffmpeg"
    ):
        path = fe.build_fast_synced_beats(
            [
                {
                    "visual": str(vis),
                    "audio": str(aud),
                    "caption": "It opens on the house.",
                    "duration_sec": 7.0,
                    "scene_id": "s01",
                }
            ],
            out_mp4,
            audio_mode="voice",
            smooth=True,
            status_out=status,
        )

    assert Path(path).is_file()
    assert status.get("captions_requested") is True
    assert status.get("captions_burn_failed") is True
    assert status.get("captions") == "requested_but_unavailable"
    assert status.get("captions") != "burned"

    primary = [c for c in calls if "drawtext=" in c and "seg_00" in c]
    fallback = [c for c in calls if "drawtext=" not in c and "seg_00" in c]
    assert primary, "expected a drawtext attempt"
    assert fallback, "expected a no-drawtext fallback"
    fb = fallback[0]
    assert "apad=whole_dur=" in fb
    assert " -t " in fb or "\t-t\t" in fb or "-t" in fb.split()
    assert "-shortest" not in fb.split()


def test_compose_propagates_caption_burn_failure(tmp_path: Path):
    p = tmp_path / "s01.mp4"
    p.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 12_000)
    scenes = [
        {
            "scene_id": "s01",
            "duration_sec": 5.0,
            "narration": "Hello captions.",
            "role": "hook",
            "visual_path": str(p),
            "search_query": "x",
        }
    ]
    req = VideoGenerationRequest(
        brief="x",
        audio_mode="mute",
        meta={"topic": "x", "creative_brief": {"captions": True}, "scenes": scenes},
    )

    def _fake_encode(beats, out_mp4, status_out=None, **kwargs):
        if status_out is not None:
            status_out.clear()
            status_out.update(
                {
                    "captions_requested": True,
                    "captions_burn_failed": True,
                    "captions": "requested_but_unavailable",
                }
            )
        out = Path(out_mp4)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 30_000)
        return out

    with patch("jarvis.mira.pipeline.out_root", return_value=tmp_path / "out"), patch(
        "jarvis.mira.fast_encode.build_fast_synced_beats", side_effect=_fake_encode
    ), patch(
        "jarvis.mira.fast_encode._probe_duration", return_value=5.0
    ):
        (tmp_path / "out" / "videos").mkdir(parents=True, exist_ok=True)
        out = compose_from_visual_paths(req, scenes, provider_id="test")

    assert out.get("ok") is True
    assert out.get("captions_requested") is True
    assert out.get("captions_burn_failed") is True
    assert out.get("captions_status") == "requested_but_unavailable"
    assert "captions=requested_but_unavailable" in (out.get("notes") or [])
    assert "captions=on" not in (out.get("notes") or [])
    q = validate_creative_output(
        {**out, "generation_kind": "legacy_stock_collage", "is_neural_video": False},
        expected_aspect="9:16",
        expected_duration_sec=5,
        planned_scene_ids=["s01"],
        narrations=["Hello captions."],
    )
    assert "captions_requested_but_unavailable" in (q.get("issues") or [])


def test_partial_cap_honesty_still_intact(monkeypatch):
    from jarvis.mira import creative_engine as eng

    monkeypatch.setenv("MIRA_HF_T2V_MAX_SCENES", "2")

    class _FakeHF:
        provider_id = "mira_hf_remote_t2v"

        def is_available(self) -> bool:
            return True

        def generate(self, request: VideoGenerationRequest) -> dict:
            scenes = list((request.meta or {}).get("scenes") or [])
            return {
                "ok": True,
                "status": "done",
                "video_path": "",
                "message": "fake",
                "scenes_handled": [s["scene_id"] for s in scenes],
                "narrations": [s.get("narration") or "" for s in scenes],
                "notes": ["timing=planned_duration"],
                "provider": self.provider_id,
                "generation_kind": "remote_t2v",
                "is_neural_video": False,
            }

    set_generation_provider(_FakeHF())
    try:
        out = eng.run_creative_video(
            "Make a 60 second cinematic story about Mars",
            duration_sec=60,
        )
        assert out.get("scenes_submitted_count") == 2
        assert out.get("scenes_deferred_by_cap")
        assert out.get("scene_cap_note")
    finally:
        set_generation_provider(None)
