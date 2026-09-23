"""Unit tests for Mira platform detect + screen-record intent (no live browser)."""

from __future__ import annotations

from jarvis.mira.platforms import detect_platform, wants_platform_record, list_platforms
from jarvis.mira.intent import expand_ask, detect_entity


def test_platforms_registered():
    keys = set(list_platforms())
    assert "huggingface" in keys
    assert "cursor" in keys
    assert "chatgpt" in keys


def test_detect_hugging_face():
    p = detect_platform("make a full video of hugging face")
    assert p is not None
    assert p["id"] == "huggingface"
    assert wants_platform_record("make a full video of hugging face")


def test_detect_cursor_and_chatgpt():
    assert detect_platform("full video of cursor")["id"] == "cursor"
    assert detect_platform("generate video of chat gpt")["id"] == "chatgpt"
    assert wants_platform_record("screen record chatgpt and make a video")


def test_expand_marks_platform_record():
    ex = expand_ask("make a full video of hugging face")
    assert ex.get("prefer_platform_record") is True
    assert detect_entity("hugging face") == "huggingface"


def test_detect_cryptorafts():
    p = detect_platform("make a full video of crypto rafts")
    assert p is not None
    assert p["id"] == "cryptorafts"
    assert wants_platform_record("full video of cryptorafts")
    assert detect_entity("crypto rafts") == "cryptorafts"


def test_platform_tour_unlimited_by_default():
    from jarvis.mira.platforms import _wants_deep_tour, _wants_quick_tour

    assert _wants_deep_tour("create a video of crypto rafts") is True
    assert _wants_quick_tour("create a video of crypto rafts") is False
    assert _wants_quick_tour("quick teaser of crypto rafts") is True
    assert _wants_deep_tour("quick teaser of crypto rafts") is False


def test_cryptorafts_has_full_step_list():
    from jarvis.mira.platforms import detect_platform, _dedupe_steps_one_url

    p = detect_platform("crypto rafts")
    assert p is not None
    assert len(p["steps"]) >= 10
    urls = [str(s["url"]).rstrip("/") for s in p["steps"]]
    assert len(urls) == len(set(urls)), "each CryptoRafts page must appear once"
    assert any("raftai-agent" in u for u in urls)
    assert any("dealflow" in u for u in urls)
    # Dedupe merges repeated home visits
    merged = _dedupe_steps_one_url(
        [
            {"url": "https://cryptorafts.com/", "line": "A", "scrolls": (0,)},
            {"url": "https://cryptorafts.com/", "line": "B", "scrolls": (1000,)},
            {"url": "https://cryptorafts.com/features", "line": "F", "scrolls": (0,)},
        ]
    )
    assert len(merged) == 2
    assert "B" in merged[0]["line"]


def test_non_platform_topic_not_forced():
    assert detect_platform("make a video of golden retrievers on a beach") is None
    assert wants_platform_record("make a video of golden retrievers on a beach") is False


def test_dismiss_overlays_helper_exists():
    from jarvis.mira.platforms import _dismiss_blocking_overlays

    assert callable(_dismiss_blocking_overlays)
    # None-safe
    assert _dismiss_blocking_overlays(None) == "skip"
