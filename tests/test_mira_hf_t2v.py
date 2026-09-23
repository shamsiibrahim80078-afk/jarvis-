"""Phase 4: Hugging Face remote text-to-video provider (mocked HTTP, no live credits)."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from jarvis.mira.generation_provider import (
    LegacyStockCollageProvider,
    UnavailableNeuralVideoProvider,
    VideoGenerationRequest,
    creative_visual_mode,
    get_generation_provider,
    get_neural_video_provider,
    set_generation_provider,
)
from jarvis.mira.hf_video_provider import (
    HuggingFaceTextToVideoProvider,
    _looks_like_mp4,
)
from jarvis.mira.video_router import requires_live_hard_lock, route_video_ask


# Minimal ISO BMFF / ftyp header — enough for marker checks (not a full playable movie)
_FAKE_MP4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isomiso2mp41" + (b"\x00" * 12_000)


def _clear_hf_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in (
        "HF_TOKEN",
        "HUGGINGFACE_HUB_TOKEN",
        "HUGGING_FACE_HUB_TOKEN",
        "MIRA_HF_T2V_MODEL",
        "MIRA_HF_T2V_PROVIDER",
    ):
        monkeypatch.delenv(k, raising=False)


def test_hf_provider_missing_token_unavailable(monkeypatch: pytest.MonkeyPatch):
    _clear_hf_env(monkeypatch)
    p = HuggingFaceTextToVideoProvider()
    assert p.is_available() is False
    reason = p.unavailable_reason().lower()
    assert "hf_token" in reason or "token" in reason
    out = p.generate(VideoGenerationRequest(brief="ocean waves at sunset"))
    assert out["ok"] is False
    assert out["status"] == "unavailable"
    assert out.get("is_neural_video") is False
    assert out.get("generation_kind") == "remote_t2v"
    assert not out.get("video_path")


def test_hf_provider_config_reads_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HF_TOKEN", "hf_test_token_not_real")
    monkeypatch.setenv("MIRA_HF_T2V_MODEL", "Wan-AI/Wan2.1-T2V-1.3B")
    monkeypatch.setenv("MIRA_HF_T2V_PROVIDER", "fal-ai")
    from jarvis.mira import hf_video_provider as mod

    assert mod._cfg_model() == "Wan-AI/Wan2.1-T2V-1.3B"
    assert mod._cfg_provider() == "fal-ai"
    assert mod._hf_token() == "hf_test_token_not_real"


def test_looks_like_mp4_marker():
    assert _looks_like_mp4(_FAKE_MP4[:64]) is True
    assert _looks_like_mp4(b"notavideo") is False


def test_mocked_hf_http_success_sets_neural(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("HF_TOKEN", "hf_test_token_not_real")
    monkeypatch.setenv("MIRA_HF_T2V_MAX_SCENES", "1")
    monkeypatch.setenv("MIRA_HF_T2V_NUM_FRAMES", "16")
    monkeypatch.setenv("MIRA_HF_T2V_PROVIDER", "fal-ai")

    # Point Mira outputs into tmp
    monkeypatch.setenv("MIRA_OUT_DIR", str(tmp_path / "out"))

    compose_result = {
        "ok": True,
        "status": "done",
        "video_path": str(tmp_path / "out" / "videos" / "final.mp4"),
        "scenes_handled": ["s01"],
        "narrations": ["A calm ocean at sunset."],
        "notes": ["compose=hf_remote_t2v"],
        "message": "ok",
        "is_neural_video": True,
        "generation_kind": "remote_t2v",
        "provider": "mira_hf_remote_t2v",
    }
    (tmp_path / "out" / "videos").mkdir(parents=True, exist_ok=True)
    (tmp_path / "out" / "videos" / "final.mp4").write_bytes(_FAKE_MP4)

    with patch(
        "jarvis.mira.hf_video_provider._fal_ai_text_to_video_via_hf_router",
        return_value=(_FAKE_MP4, ["hf_fal_id_remap=fal-ai/wan-t2v"]),
    ), patch(
        "jarvis.mira.hf_video_provider._hub_available", return_value=True
    ), patch(
        "jarvis.mira.creative_compose.compose_from_visual_paths", return_value=compose_result
    ), patch(
        "jarvis.mira.pipeline.out_root", return_value=tmp_path / "out"
    ):
        p = HuggingFaceTextToVideoProvider()
        assert p.is_available() is True
        req = VideoGenerationRequest(
            brief="ocean waves",
            meta={
                "scenes": [
                    {
                        "scene_id": "s01",
                        "visual_prompt": "cinematic ocean waves at golden hour",
                        "narration": "A calm ocean at sunset.",
                        "role": "hook",
                        "search_query": "ocean waves",
                    }
                ]
            },
        )
        out = p.generate(req)

    assert out["ok"] is True
    assert out.get("is_neural_video") is True
    assert out.get("generation_kind") == "remote_t2v"
    assert out.get("provider") == "mira_hf_remote_t2v"
    assert out.get("video_path")
    assert Path(out["video_path"]).is_file()


def test_mocked_hf_http_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("HF_TOKEN", "hf_test_token_not_real")
    monkeypatch.setenv("MIRA_HF_T2V_MAX_SCENES", "1")
    monkeypatch.setenv("MIRA_HF_T2V_PROVIDER", "fal-ai")

    with patch(
        "jarvis.mira.hf_video_provider._fal_ai_text_to_video_via_hf_router",
        side_effect=RuntimeError("HF/fal T2V error: Path /v2.1/1.3b/text-to-video not found"),
    ), patch(
        "jarvis.mira.hf_video_provider._hub_available", return_value=True
    ), patch(
        "jarvis.mira.pipeline.out_root", return_value=tmp_path / "out"
    ):
        (tmp_path / "out").mkdir(parents=True, exist_ok=True)
        p = HuggingFaceTextToVideoProvider()
        out = p.generate(
            VideoGenerationRequest(
                brief="stormy sky",
                meta={
                    "scenes": [
                        {
                            "scene_id": "s01",
                            "visual_prompt": "storm clouds",
                            "narration": "Thunder rolls.",
                            "role": "hook",
                            "search_query": "storm",
                        }
                    ]
                },
            )
        )

    assert out["ok"] is False
    assert out.get("is_neural_video") is False
    assert out.get("generation_kind") == "remote_t2v"
    assert not out.get("video_path")
    assert "Path" in (out.get("message") or "") or "error" in (out.get("message") or "").lower()


def test_extract_video_url_success_and_detail_error():
    from jarvis.mira.hf_video_provider import _extract_video_url

    url = _extract_video_url({"video": {"url": "https://example.com/a.mp4"}})
    assert url.endswith("a.mp4")
    try:
        _extract_video_url({"detail": "Path /v2.1/1.3b/text-to-video not found"})
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "Path" in str(exc)


def test_auto_mode_prefers_hf_when_available(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MIRA_CREATIVE_VISUAL_MODE", "auto")
    monkeypatch.setenv("HF_TOKEN", "hf_test_token_not_real")
    set_generation_provider(None)
    with patch("jarvis.mira.hf_video_provider._hub_available", return_value=True):
        p = get_generation_provider()
        assert isinstance(p, HuggingFaceTextToVideoProvider)
        assert p.is_available() is True
    set_generation_provider(None)


def test_auto_mode_falls_back_to_legacy_without_token(monkeypatch: pytest.MonkeyPatch):
    _clear_hf_env(monkeypatch)
    monkeypatch.setenv("MIRA_CREATIVE_VISUAL_MODE", "auto")
    set_generation_provider(None)
    p = get_generation_provider()
    assert isinstance(p, LegacyStockCollageProvider)
    set_generation_provider(None)


def test_neural_only_without_token_unavailable(monkeypatch: pytest.MonkeyPatch):
    _clear_hf_env(monkeypatch)
    monkeypatch.setenv("MIRA_CREATIVE_VISUAL_MODE", "neural_only")
    set_generation_provider(None)
    p = get_generation_provider()
    assert p.is_available() is False
    out = p.generate(VideoGenerationRequest(brief="city night"))
    assert out["ok"] is False
    assert out.get("is_neural_video") is False
    assert not out.get("video_path")
    set_generation_provider(None)


def test_legacy_mode_never_claims_neural(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MIRA_CREATIVE_VISUAL_MODE", "legacy")
    monkeypatch.setenv("HF_TOKEN", "hf_test_token_not_real")
    set_generation_provider(None)
    with patch("jarvis.mira.hf_video_provider._hub_available", return_value=True):
        p = get_generation_provider()
        assert isinstance(p, LegacyStockCollageProvider)
    set_generation_provider(None)


def test_get_neural_returns_unavailable_without_creds(monkeypatch: pytest.MonkeyPatch):
    _clear_hf_env(monkeypatch)
    set_generation_provider(None)
    p = get_neural_video_provider()
    assert isinstance(p, UnavailableNeuralVideoProvider)
    assert p.is_available() is False


def test_creative_engine_uses_injected_hf_metadata(monkeypatch: pytest.MonkeyPatch):
    """Engine must surface provider metadata + is_neural_video from provider result."""
    from jarvis.mira import creative_engine as eng

    class _FakeHF:
        provider_id = "mira_hf_remote_t2v"

        def is_available(self) -> bool:
            return True

        def generate(self, request: VideoGenerationRequest) -> dict:
            return {
                "ok": True,
                "status": "done",
                "video_path": "",  # empty → quality soft/hard path
                "message": "fake",
                "scenes_handled": ["s01"],
                "narrations": ["line"],
                "notes": ["hf_model=Wan-AI/Wan2.1-T2V-1.3B"],
                "provider": self.provider_id,
                "generation_kind": "remote_t2v",
                "is_neural_video": False,  # honest: no real file
                "hf_model": "Wan-AI/Wan2.1-T2V-1.3B",
                "hf_inference_provider": "fal-ai",
            }

    set_generation_provider(_FakeHF())
    try:
        out = eng.run_creative_video("cinematic ocean waves", duration_sec=20)
        assert out.get("provider") == "mira_hf_remote_t2v"
        assert out.get("generation_kind") == "remote_t2v"
        assert out.get("is_neural_video") is False
        assert out.get("video_pipeline") == "creative_generative"
        assert "hf_model=Wan-AI/Wan2.1-T2V-1.3B" in (out.get("notes") or [])
    finally:
        set_generation_provider(None)


def test_live_screen_routing_untouched():
    live = route_video_ask("record a product demo of CryptoRafts")
    assert live.pipeline == "live_screen"
    assert requires_live_hard_lock(live)
    creative = route_video_ask("Make a cinematic video about ocean waves")
    assert creative.pipeline == "creative_generative"
    assert not requires_live_hard_lock(creative)


def test_mp4_fixture_validation_helper(tmp_path: Path):
    """Tiny fixture path: write bytes with ftyp; validate marker + size gate."""
    clip = tmp_path / "tiny.mp4"
    clip.write_bytes(_FAKE_MP4)
    assert clip.stat().st_size > 8_000
    assert _looks_like_mp4(clip.read_bytes()[:64]) is True
