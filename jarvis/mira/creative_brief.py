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
    # Explicit user VO / story beats (Phase 5C-1) — planner must not overwrite these
    script_lines: list[str] = field(default_factory=list)
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


_SCRIPT_MARKER = re.compile(
    r"\b(?:script|narration|voice[\s-]?over|dialogue|vo\s*lines?)\s*[:=]\s*(.+)$",
    re.I,
)
_CHROME_SENTENCE = re.compile(
    r"^(?:mira[,:]?\s*)?(?:please\s+)?(?:make|create|generate|produce)\b|"
    r"\b(?:youtube\s+)?(?:shorts?|reels?|tiktok|video|clip|film)\b|"
    r"\b\d+\s*(?:s|sec|secs|second|seconds)\b|"
    r"\b(?:9|16)\s*[:x]\s*(?:16|9)\b|"
    r"\b(?:captions?|subtitles?|mute|silent)\b",
    re.I,
)
_DURATION_TOKEN = re.compile(
    r"\b\d+\s*(?:s|sec|secs|second|seconds)\b",
    re.I,
)
_ASPECT_TOKEN = re.compile(r"\b(?:9|16)\s*[:x]\s*(?:16|9)\b", re.I)
_EXPLICIT_PACING_FAST = re.compile(
    r"\b(?:fast[\s-]?paced|quick\s+cuts?|rapid\s+pacing|pacing\s*[:=]\s*fast)\b",
    re.I,
)
_EXPLICIT_PACING_CLEAR = re.compile(
    r"\b(?:clear\s+pacing|slow(?:er)?\s+pacing|explanatory\s+pacing|"
    r"pacing\s*[:=]\s*clear|pace\s*[:=]\s*clear)\b",
    re.I,
)
_EXPLICIT_PACING_MEDIUM = re.compile(
    r"\b(?:medium\s+pacing|balanced\s+pacing|pacing\s*[:=]\s*medium)\b",
    re.I,
)


def extract_script_lines(ask: str) -> list[str]:
    """Pull explicit user VO/story beats from free-form ask. Empty if none.

    Only when the ask clearly marks a script (Script:/Narration:/Dialogue:,
    numbered dialogue beats, or quoted lines inside a script marker).
    Ordinary quoted topic words are NOT treated as narration.
    """
    text = re.sub(r"\s+", " ", (ask or "").strip())
    if not text:
        return []

    found: list[str] = []

    # 1) Explicit marker block: Script: A | B | C  or  Narration: "a" "b"
    m = _SCRIPT_MARKER.search(text)
    if m:
        body = m.group(1).strip()
        quoted = re.findall(r"[\"“”]([^\"“”]{6,160})[\"“”]", body)
        if len(quoted) >= 1:
            found = [q.strip()[:160] for q in quoted if q.strip()]
        if not found:
            parts = re.split(r"\s*[|;]\s*|\s*\d+[.)]\s+", body)
            for p in parts:
                p = p.strip(" .,:;-")
                if len(p) >= 6:
                    found.append(p[:160])

    # 2) Numbered dialogue/script beats (require ≥2 to avoid lone outlines)
    if not found:
        numbered = re.findall(
            r"(?:^|\s)\d+[.)]\s+([^|;]+?)(?=(?:\s+\d+[.)]\s+|$))",
            text,
        )
        cleaned = []
        for p in numbered:
            p = p.strip(" .,:;-")
            if len(p) >= 6 and not _CHROME_SENTENCE.search(p):
                cleaned.append(p[:160])
        if len(cleaned) >= 2:
            found = cleaned

    # 3) Explicit story/plot/narration body with multiple sentences (marker required)
    if not found:
        story_m = re.search(
            r"\b(?:story|plot)\s*[:=]\s*(.+)$",
            text,
            re.I,
        )
        if story_m:
            candidate = story_m.group(1).strip()
            sents = [
                s.strip(" .,:;-")
                for s in re.split(r"(?<=[.!?])\s+", candidate)
                if s.strip()
            ]
            usable = [
                s[:160]
                for s in sents
                if len(s) >= 12 and not _CHROME_SENTENCE.search(s)
            ]
            if len(usable) >= 2:
                found = usable

    # Dedupe preserve order
    out: list[str] = []
    seen: set[str] = set()
    for line in found:
        key = re.sub(r"\s+", " ", line.lower()).strip()
        if key and key not in seen:
            seen.add(key)
            out.append(line)
    return out[:10]


def _core_topic_from_ask(raw: str) -> str:
    """Extract subject topic; strip request chrome, duration, and aspect syntax."""
    text = re.sub(r"\s+", " ", (raw or "").strip())
    if not text:
        return "cinematic scene"

    # Drop explicit script/narration blocks from the topic candidate
    text = _SCRIPT_MARKER.sub("", text).strip(" .,:;-") or text
    # Drop numbered beat tails that look like script lists
    text = re.sub(r"(?:^|\s)\d+[.)]\s+.+$", "", text).strip(" .,:;-") or text

    # Prefer the phrase after about/of/on/for (request syntax)
    about = re.search(
        r"\b(?:about|of|on|for)\s+(.+)$",
        text,
        re.I,
    )
    if about:
        core = about.group(1).strip(" .,:;-")
    else:
        core = re.sub(
            r"^(?:mira[,:]?\s*)?(?:please\s+)?(?:make|create|generate|produce)\s+"
            r"(?:me\s+)?(?:an?\s+)?",
            "",
            text,
            flags=re.I,
        ).strip(" .,:;-") or text

    # Drop trailing explicit pacing / audio chrome from the subject phrase
    core = re.sub(
        r"\s+(?:with\s+)?(?:clear\s+pacing|slow(?:er)?\s+pacing|explanatory\s+pacing|"
        r"fast[\s-]?paced|quick\s+cuts?|medium\s+pacing|balanced\s+pacing|"
        r"pacing\s*[:=]\s*\w+|captions?|subtitles?|music|soundtrack)\s*$",
        "",
        core,
        flags=re.I,
    ).strip(" .,:;-")

    # Remove duration / aspect request tokens
    core = _DURATION_TOKEN.sub(" ", core)
    core = _ASPECT_TOKEN.sub(" ", core)
    # Leading media-type chrome still stuck before the subject
    core = re.sub(
        r"^(?:(?:an?\s+)?(?:mute|silent|cinematic|funny|realistic|suspenseful|clear)\s+)*"
        r"(?:youtube\s+)?(?:shorts?|reels?|tiktok|video|clip|film|story|explainer|promo)\s+",
        "",
        core,
        flags=re.I,
    ).strip(" .,:;-")
    # Orphan "video/story" words left as pure chrome
    core = re.sub(
        r"^(?:shorts?|reels?|tiktok|video|clip|film|story|explainer|promo)\b\s*",
        "",
        core,
        flags=re.I,
    ).strip(" .,:;-")
    core = re.sub(r"\s+", " ", core).strip(" .,:;-")
    return (core or text)[:200]


def build_creative_brief(
    ask: str,
    *,
    duration_sec: int | None = None,
    aspect: str | None = None,
    search_hints: list[str] | None = None,
    audio_mode: str = "voice",
    script_lines: list[str] | None = None,
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
    dm = _DURATION_TOKEN.search(raw)
    if dm:
        num_m = re.search(r"(\d+)", dm.group(0))
        if num_m:
            dur = max(8, min(180, int(num_m.group(1))))
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
    # Only explicit pacing instructions override (not topic adjectives like "clear skies")
    if _EXPLICIT_PACING_FAST.search(raw):
        pacing = "fast"
    elif _EXPLICIT_PACING_CLEAR.search(raw):
        pacing = "clear"
    elif _EXPLICIT_PACING_MEDIUM.search(raw):
        pacing = "medium"

    topic = _core_topic_from_ask(raw)

    n = _scene_count_for(dur, purpose)
    continuity = (
        f"Keep visual continuity on: {topic}. Same world, lighting family, and subject identity."
    )

    user_lines: list[str] = []
    if script_lines:
        user_lines = [str(s).strip()[:160] for s in script_lines if str(s).strip()][:10]
    if not user_lines:
        user_lines = extract_script_lines(raw)

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
        script_lines=user_lines,
        extras={"audio_mode": audio_mode},
    )

