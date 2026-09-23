"""Smoke tests for Jarvis Mira (no network required for parse/status)."""

from jarvis.mira.model import generate, model_identity
from jarvis.mira.quality import audience_script, enhance_still_prompt
from jarvis.tools.mira_tool import is_mira_generate_intent, is_youtube_watch_intent, parse_mira_command


def test_identity():
    ident = model_identity()
    assert ident["model_id"].startswith("mira_jarvis_v")
    assert ident["is_trained_foundation_model"] is False


def test_enhance_prompt_adds_quality():
    p = enhance_still_prompt("AI agent office morning")
    assert "cinematic" in p.lower() or "photoreal" in p.lower()
    assert "watermark" in p.lower() or "no text" in p.lower()


def test_audience_script_has_hook():
    s = audience_script("building Jarvis", seconds=30)
    assert "Jarvis" in s or "building" in s.lower()
    assert len(s) > 40


def test_parse_video_without_saying_mira():
    p = parse_mira_command("make a video about cats dancing in rain 20 seconds")
    assert p is not None
    assert p["action"] == "video"
    assert "cat" in p["topic"].lower()
    assert "20 seconds" not in p["topic"].lower()


def test_parse_any_topic_not_just_office():
    p = parse_mira_command("create a video about space rockets")
    assert p is not None
    assert "rocket" in p["topic"].lower() or "space" in p["topic"].lower()


def test_parse_image_command():
    p = parse_mira_command("create an image of a futuristic desk")
    assert p is not None
    assert p["action"] == "image"
    assert "desk" in p["topic"].lower()


def test_parse_rate():
    p = parse_mira_command("rate this video 5")
    assert p is not None
    assert p["action"] == "rate"
    assert p["rating"] == "5"


def test_youtube_search_not_mira():
    assert is_youtube_watch_intent("search for funny cats on youtube")
    assert not is_mira_generate_intent("search for funny cats on youtube")
    assert is_mira_generate_intent("make a video about funny cats")


def test_chained_command_takes_video_topic_clean():
    p = parse_mira_command(
        "make a video about agent office morning 30 seconds create an image of a desk"
    )
    assert p is not None
    assert p["action"] == "video"
    assert "desk" not in p["topic"].lower()


def test_generate_help():
    out = generate("help")
    assert out.get("ok") is True
    assert "Mira" in (out.get("message") or "")
