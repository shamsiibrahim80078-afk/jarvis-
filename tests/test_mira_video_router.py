"""Phase 1: Mira video_router regression tests (no network / no Playwright)."""

from __future__ import annotations

from jarvis.mira.generation_provider import (
    UnimplementedGenerationProvider,
    VideoGenerationRequest,
    get_generation_provider,
    get_neural_video_provider,
    set_generation_provider,
)
from jarvis.mira.intent import expand_ask
from jarvis.mira.video_router import (
    prefer_platform_record,
    requires_live_hard_lock,
    route_video_ask,
)
from jarvis.tools.mira_tool import parse_mira_command


def test_product_asks_route_live_screen():
    cases = [
        "Record a demo of Gemini",
        "full video of cryptorafts",
        "create a video of eleven labs api key",
        "make a video of cursor",
        "video of stripe docs",
    ]
    for ask in cases:
        r = route_video_ask(ask)
        assert r.pipeline == "live_screen", (ask, r)
        assert r.hard_lock_live is True
        assert r.prefer_platform_record is True
        assert requires_live_hard_lock(r) is True
        assert r.platform is not None, ask


def test_creative_asks_route_creative_generative():
    cases = [
        "Show me an AI robot working in a futuristic office",
        "Make a cinematic detective story",
        "video of dogs playing in the park",
        "sunset beach cinematic short",
    ]
    for ask in cases:
        r = route_video_ask(ask)
        assert r.pipeline == "creative_generative", (ask, r.pipeline, r.reasons)
        assert r.hard_lock_live is False
        assert prefer_platform_record(r) is False
        assert r.platform is None


def test_hybrid_asks_route_hybrid_and_still_hard_lock():
    ask = (
        "Record a full demo of Gemini and then show a cinematic explanation "
        "of how the AI works"
    )
    r = route_video_ask(ask)
    assert r.pipeline == "hybrid", (r.pipeline, r.reasons)
    assert r.hard_lock_live is True
    assert r.prefer_platform_record is True
    assert r.platform is not None
    assert r.platform.get("id") == "gemini"


def test_hard_lock_never_sends_product_to_creative():
    """Regression: product demos must not be classified as creative_generative."""
    for ask in (
        "create a video of hugging face",
        "full video of crypto rafts",
        "eleven labs api key video",
        "openai api key video",
    ):
        r = route_video_ask(ask)
        assert r.pipeline in ("live_screen", "hybrid"), ask
        assert r.pipeline != "creative_generative"
        assert requires_live_hard_lock(r)


def test_expand_ask_prefers_platform_via_router():
    ex = expand_ask("make a full video of hugging face")
    assert ex.get("prefer_platform_record") is True
    assert ex.get("video_pipeline") in ("live_screen", "hybrid")


def test_expand_ask_creative_not_platform():
    ex = expand_ask("make a cinematic detective story")
    assert ex.get("prefer_platform_record") is False
    assert ex.get("video_pipeline") == "creative_generative"


def test_parse_mira_command_exposes_pipeline():
    live = parse_mira_command("create a video of gemini")
    assert live is not None
    assert live.get("platform_tour") is True
    assert live.get("video_pipeline") in ("live_screen", "hybrid")

    creative = parse_mira_command("make a video about cats dancing in rain")
    assert creative is not None
    assert creative.get("platform_tour") is False
    assert creative.get("video_pipeline") == "creative_generative"


def test_generation_provider_not_implemented_explicit():
    from jarvis.mira.generation_provider import (
        UnavailableNeuralVideoProvider,
        set_generation_provider,
        get_neural_video_provider,
    )

    set_generation_provider(UnavailableNeuralVideoProvider())
    try:
        p = get_neural_video_provider()
        assert p.is_available() is False
        out = p.generate(VideoGenerationRequest(brief="futuristic robot office"))
        assert out.get("ok") is False
        assert out.get("status") in ("unavailable", "not_implemented")
        assert not out.get("video_path")
        assert out.get("is_neural_video") is False
    finally:
        set_generation_provider(None)


def test_lifestyle_not_hard_locked():
    r = route_video_ask("bangkok city tour travel video")
    assert r.pipeline == "creative_generative"
    assert requires_live_hard_lock(r) is False
