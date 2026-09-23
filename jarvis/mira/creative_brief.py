"""Structured creative brief for Mira Phase 2 (inferred from free-form asks)."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Purpose = Literal[
    "story",
    "explainer",
    "comedy",
    "suspense",
    "promo",
    "lifestyle",
    "general",
]


@dataclass
class CreativeBrief:
    topic: str
    purpose: Purpose = "general"
    audience: str = "general viewers"
    duration_sec: int = 30
    aspect: str = "9:16"
    visual_style: str = "cinematic"
    tone: str = "neutral"
    pacing: str = "medium"
    narration: bool = True
    captions: bool = False
    music: bool = False
    sfx: bool = False
    scene_count: int = 4
    continuity: str = "same subject and setting across scenes"
    original_ask: str = ""
    search_hints: list[str] = field(default_factory=list)
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _detect_purpose(text: str) -> Purpose:
    t = (text or "").lower()
    if re.search(r"\b(explain|explainer|how\s+\w+\s+works|what\s+is|educational|facts?\s+about)\b", t):
        return "explainer"
    if re.search(r"\b(funny|comedy|hilarious|joke|office\s+workers?)\b", t):
        return "comedy"
    if re.search(r"\b(suspense|horror|scary|abandoned|thriller|mystery)\b", t):
        return "suspense"
    if re.search(r"\b(story|detective|astronaut|discover|adventure|tale)\b", t):
        return "story"
    if re.search(r"\b(promo|advert|commercial|product\s+ad)\b", t):
        return "promo"
    if re.search(r"\b(lifestyle|vlog|day\s+in\s+the\s+life)\b", t):
        return "lifestyle"
    return "general"


def _detect_tone(text: str, purpose: Purpose) -> str:
    try:
        from jarvis.mira.formats import detect_mood

        m = detect_mood(text)
        if m:
            return str(m)
    except Exception:
        pass
    defaults = {
        "comedy": "funny",
        "suspense": "tense",
        "story": "cinematic",
        "explainer": "clear",
        "promo": "upbeat",
        "lifestyle": "warm",
        "general": "neutral",
    }
    return defaults.get(purpose, "neutral")


def _detect_style(text: str, purpose: Purpose) -> str:
    t = (text or "").lower()
    if re.search(r"\b(realistic|photoreal|documentary)\b", t):
        return "photoreal"
    if re.search(r"\b(cinematic|film|trailer)\b", t):
        return "cinematic"
    if re.search(r"\b(cartoon|animated|anime)\b", t):
        return "stylized"
    if purpose == "explainer":
        return "clean explanatory"
    if purpose == "comedy":
        return "light comedic"
    if purpose == "suspense":
        return "dark atmospheric"
    return "cinematic"


def _scene_count_for(duration_sec: int, purpose: Purpose) -> int:
    if duration_sec <= 15:
        return 3
    if duration_sec <= 30:
        return 4 if purpose != "explainer" else 5
    if duration_sec <= 60:
        return 6
    return 8


def build_creative_brief(
    ask: str,
    *,
    duration_sec: int | None = None,
    aspect: str | None = None,
    search_hints: list[str] | None = None,
    audio_mode: str = "voice",
) -> CreativeBrief:
    """Infer a usable CreativeBrief from a free-form user ask (no interrogation)."""
    raw = re.sub(r"\s+", " ", (ask or "").strip())
    if not raw:
        raw = "cinematic scene"

    purpose = _detect_purpose(raw)
    tone = _detect_tone(raw, purpose)
    style = _detect_style(raw, purpose)

    dur = int(duration_sec or 0)
    asp = (aspect or "").strip()
    try:
        from jarvis.mira.formats import apply_format, detect_format

        fmt = detect_format(raw)
        applied = apply_format(fmt, aspect=asp or None, duration_sec=dur or None)
        if not asp:
            asp = str(applied.get("aspect") or "9:16")
        if dur <= 0:
            dur = int(applied.get("duration_sec") or 30)
    except Exception:
        if not asp:
            asp = "9:16"
        if dur <= 0:
            dur = 30

    # Explicit duration/aspect in the ask win
    dm = re.search(r"(\d+)\s*(?:s|sec|secs|seconds)\b", raw, re.I)
    if dm:
        dur = max(8, min(180, int(dm.group(1))))
    if re.search(r"\b(9\s*[:x]\s*16|vertical|shorts?|reels?|tiktok)\b", raw, re.I):
        asp = "9:16"
    elif re.search(r"\b(16\s*[:x]\s*9|landscape|widescreen|youtube\s+video)\b", raw, re.I):
        asp = "16:9"

    narr = (audio_mode or "voice").lower() in ("voice", "both")
    captions = bool(re.search(r"\b(captions?|subtitles?|on[\s-]?screen\s+text)\b", raw, re.I))
    music = bool(re.search(r"\b(music|soundtrack|bgm|score)\b", raw, re.I))
    sfx = bool(re.search(r"\b(sfx|sound\s*effects?|foley)\b", raw, re.I))

    pacing = "fast" if purpose in ("comedy", "suspense") or dur <= 20 else "medium"
    if purpose == "explainer":
        pacing = "clear"

    # Strip chrome for topic core
    topic = re.sub(
        r"^(?:mira[,:]?\s*)?(?:please\s+)?(?:make|create|generate|produce)\s+"
        r"(?:me\s+)?(?:an?\s+)?(?:mute\s+|silent\s+)?"
        r"(?:cinematic\s+|funny\s+|realistic\s+|suspenseful\s+)?"
        r"(?:youtube\s+)?(?:shorts?|reels?|video|clip|film)\s+"
        r"(?:about|of|on|for)?\s*",
        "",
        raw,
        flags=re.I,
    ).strip(" .,:;-") or raw
    topic = re.sub(
        r"\b\d+\s*(?:s|sec|secs|seconds)\b|\b(?:9|16)\s*[:x]\s*(?:16|9)\b",
        " ",
        topic,
        flags=re.I,
    )
    topic = re.sub(r"\s+", " ", topic).strip() or raw

    n = _scene_count_for(dur, purpose)
    continuity = (
        f"Keep visual continuity on: {topic}. Same world, lighting family, and subject identity."
    )

    return CreativeBrief(
        topic=topic[:200],
        purpose=purpose,
        audience="general viewers",
        duration_sec=dur,
        aspect=asp,
        visual_style=style,
        tone=tone,
        pacing=pacing,
        narration=narr,
        captions=captions,
        music=music,
        sfx=sfx,
        scene_count=n,
        continuity=continuity,
        original_ask=raw[:300],
        search_hints=[str(h).strip()[:80] for h in (search_hints or []) if str(h).strip()][:8],
        extras={"audio_mode": audio_mode},
    )
