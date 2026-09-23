"""Mood → Edge TTS voice mapping for Shorts variety."""

from __future__ import annotations

_MOOD_VOICES: dict[str, str] = {
    "motivational": "en-US-GuyNeural",
    "funny": "en-US-ChristopherNeural",
    "calm": "en-US-JennyNeural",
    "chill": "en-US-JennyNeural",
    "epic": "en-US-DavisNeural",
    "curious": "en-US-AndrewNeural",
    "romantic": "en-US-AriaNeural",
    "documentary": "en-GB-RyanNeural",
}

_DEFAULT = "en-US-AndrewNeural"


def voice_for_mood(mood: str | None = None) -> str:
    m = (mood or "").strip().lower()
    return _MOOD_VOICES.get(m, _DEFAULT)


def rate_for_mood(mood: str | None = None) -> str:
    m = (mood or "").strip().lower()
    if m in ("funny", "epic", "motivational"):
        return "+8%"
    if m in ("calm", "chill", "romantic"):
        return "-5%"
    return "+0%"
