"""Mira output formats — YouTube, Shorts, Reels, Stories, TikTok, etc."""

from __future__ import annotations

import re
from typing import Any

# Canonical presets users can pick after giving a creative brief
FORMATS: dict[str, dict[str, Any]] = {
    "youtube": {
        "label": "YouTube video",
        "aspect": "16:9",
        "duration_sec": 28,
        "aliases": (
            "youtube", "yt", "youtube video", "long youtube", "landscape",
            "full youtube", "yt video", "16:9", "16x9",
        ),
    },
    "youtube_shorts": {
        "label": "YouTube Shorts",
        "aspect": "9:16",
        "duration_sec": 20,
        "aliases": (
            "youtube shorts", "yt shorts", "shorts", "short", "youtube short",
            "yt short", "9:16", "9x16",
        ),
    },
    "instagram_reels": {
        "label": "Instagram Reels",
        "aspect": "9:16",
        "duration_sec": 30,
        "aliases": (
            "instagram reels", "ig reels", "reels", "reel", "insta reels",
            "insta reel", "ig reel",
        ),
    },
    "instagram_stories": {
        "label": "Instagram Stories",
        "aspect": "9:16",
        "duration_sec": 15,
        "aliases": (
            "instagram stories", "ig stories", "stories", "story",
            "insta stories", "insta story", "ig story",
        ),
    },
    "tiktok": {
        "label": "TikTok",
        "aspect": "9:16",
        "duration_sec": 30,
        "aliases": ("tiktok", "tik tok", "tt"),
    },
    "facebook_reels": {
        "label": "Facebook Reels",
        "aspect": "9:16",
        "duration_sec": 30,
        "aliases": ("facebook reels", "fb reels", "facebook reel", "fb reel"),
    },
}

MOODS: dict[str, dict[str, str]] = {
    "funny": {
        "label": "funny",
        "vo_hint": "witty playful humor, light jokes, upbeat",
        "aliases": "funny|hilarious|comedy|comedic|humorous|joke|jokes|lol|meme",
    },
    "sad": {
        "label": "sad",
        "vo_hint": "emotional melancholic soft sincere",
        "aliases": "sad|emotional|melancholy|tearful|heartbreaking|somber",
    },
    "angry": {
        "label": "angry",
        "vo_hint": "intense fiery confrontational powerful",
        "aliases": "angry|mad|furious|rage|intense|aggressive|hype rage",
    },
    "epic": {
        "label": "epic",
        "vo_hint": "cinematic grand heroic dramatic",
        "aliases": "epic|cinematic|heroic|grand|dramatic|trailer",
    },
    "calm": {
        "label": "calm",
        "vo_hint": "peaceful soothing gentle mindful",
        "aliases": "calm|peaceful|chill|relaxing|soothing|zen|soft",
    },
    "romantic": {
        "label": "romantic",
        "vo_hint": "warm intimate tender romantic",
        "aliases": "romantic|love|loving|intimate|tender|sweet",
    },
    "scary": {
        "label": "scary",
        "vo_hint": "dark suspenseful eerie tense",
        "aliases": "scary|horror|spooky|creepy|eerie|thriller",
    },
    "motivational": {
        "label": "motivational",
        "vo_hint": "inspiring confident energetic empowering",
        "aliases": "motivational|inspiring|motivation|hype|pump|empowering",
    },
}


def detect_format(text: str) -> str | None:
    """Return format key if user named one, else None."""
    lower = (text or "").lower()
    # Prefer longer aliases first
    ranked: list[tuple[int, str]] = []
    for key, meta in FORMATS.items():
        for alias in meta["aliases"]:
            if re.search(rf"\b{re.escape(alias)}\b", lower):
                ranked.append((len(alias), key))
    if not ranked:
        return None
    ranked.sort(key=lambda x: x[0], reverse=True)
    return ranked[0][1]


def detect_mood(text: str) -> str | None:
    lower = (text or "").lower()
    for key, meta in MOODS.items():
        if re.search(rf"\b(?:{meta['aliases']})\b", lower):
            return key
    return None


def apply_format(fmt: str | None, *, aspect: str = "16:9", duration_sec: int | str = 30) -> dict[str, Any]:
    """Merge a format preset onto aspect/duration.

    Requested duration wins when longer than the preset (full platform tours need it).
    """
    try:
        dur = int(duration_sec)
    except (TypeError, ValueError):
        dur = 30
    if fmt and fmt in FORMATS:
        preset = FORMATS[fmt]
        preset_dur = int(preset["duration_sec"])
        # Allow longer asks (full platform explore) without being clamped to preset
        out_dur = max(preset_dur, dur) if dur >= preset_dur else preset_dur
        out_dur = max(12, min(180, out_dur))
        return {
            "format": fmt,
            "format_label": preset["label"],
            "aspect": preset["aspect"],
            "duration_sec": out_dur,
        }
    return {
        "format": fmt or ("youtube_shorts" if aspect == "9:16" else "youtube"),
        "format_label": FORMATS.get(fmt or "", {}).get("label")
        or ("YouTube Shorts" if aspect == "9:16" else "YouTube video"),
        "aspect": aspect if aspect in ("16:9", "9:16") else "16:9",
        "duration_sec": max(12, min(180, dur)),
    }


def format_menu(brief: str, *, mood: str | None = None) -> str:
    """Ask the user which platform format (and optional mood) they want."""
    mood_line = f"\nDetected mood so far: **{mood}**." if mood else ""
    return (
        f"Got your idea: “{brief[:120]}”.{mood_line}\n\n"
        "What should I make this for? (default = Shorts for growth)\n"
        "2) YouTube Shorts (9:16) ← recommended\n"
        "1) YouTube video (16:9)\n"
        "3) Instagram Reels (9:16)\n"
        "4) Instagram Stories (9:16, ~15s)\n"
        "5) TikTok (9:16)\n"
        "6) Facebook Reels (9:16)\n\n"
        "Optional mood: funny · sad · angry · epic · calm · romantic · scary · motivational\n"
        "Reply like: `shorts funny` or `youtube video` or `reels`."
    )


def looks_like_new_brief(text: str) -> bool:
    """True when the user is starting a NEW idea — not answering the format menu."""
    lower = (text or "").lower().strip()
    if not lower:
        return False
    # Pure menu answers: "2", "shorts funny", "reels", "tiktok epic"
    if re.match(r"^[\s#]*[1-6]\b", lower) and len(lower.split()) <= 4:
        return False
    if re.search(
        r"\b(make|create|generate|produce|shoot|render|build)\b.{0,80}\b"
        r"(video|short|shorts|reel|reels|clip|film|movie|image|picture)\b",
        lower,
    ) and re.search(r"\b(about|on|of|showing|featuring|with)\b", lower):
        return True
    if re.search(
        r"\b(i\s+want|i\s+need|i'?d\s+like|can\s+you|please)\b.{0,60}\b"
        r"(video|short|shorts|reel|clip)\b.{0,40}\b(about|on|of)\b",
        lower,
    ):
        return True
    # Long freeform with a clear about-X topic
    if len(lower.split()) >= 6 and re.search(r"\babout\s+[a-z0-9][\w\s-]{2,}", lower):
        return True
    return False


def parse_format_reply(text: str) -> dict[str, Any] | None:
    """Parse a reply to the format menu. Returns {format, mood?} or None.

    Never treats a full new creative brief as a format/mood answer — that reused
    the previous pending topic (A visuals + B words).
    """
    lower = (text or "").lower().strip()
    if not lower:
        return None
    if looks_like_new_brief(lower):
        return None
    # Numbered choices
    num_map = {
        "1": "youtube",
        "2": "youtube_shorts",
        "3": "instagram_reels",
        "4": "instagram_stories",
        "5": "tiktok",
        "6": "facebook_reels",
    }
    m = re.match(r"^[\s#]*([1-6])\b", lower)
    fmt = num_map.get(m.group(1)) if m else detect_format(lower)
    mood = detect_mood(lower)
    # Bare mood-only while pending is OK if they already had format — handled by caller
    if not fmt and not mood:
        # Common shorthand
        if re.search(r"\b(vertical|portrait)\b", lower):
            fmt = "youtube_shorts"
        elif re.search(r"\b(horizontal|landscape|wide)\b", lower):
            fmt = "youtube"
    # Mood alone on a long sentence that mentions a new subject → not a menu reply
    if mood and not fmt and len(lower.split()) >= 5 and re.search(r"\babout\b", lower):
        return None
    if not fmt and not mood:
        return None
    out: dict[str, Any] = {}
    if fmt:
        out["format"] = fmt
    if mood:
        out["mood"] = mood
    return out
