"""Mira video pipeline router — single decision for live vs creative vs hybrid.

Phase 1: consolidates duplicated hard-lock / platform routing so every entry
point asks one question: which video universe does this ask belong to?

Does NOT implement generative video. Does NOT change how live tours record.
Live / product asks still hard-lock to screen-record (never stock/AI portraits).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

PipelineKind = Literal["live_screen", "creative_generative", "hybrid"]

# Extra creative / story signals — used only to mark HYBRID when a live product
# ask ALSO asks for cinematic / invented scenes (architecture for a future engine).
_CREATIVE_EXTRA_RE = re.compile(
    r"\b("
    r"cinematic|detective\s+story|short\s+film|movie\s+scene|story\s+about|"
    r"futuristic\s+office|ai\s+robot|robots?\s+working|fantasy|dream\s+sequence|"
    r"imagine|fictional|animated\s+explanation|cinematic\s+explanation|"
    r"then\s+(show|add|generate|create)\s+(a\s+)?(cinematic|ai|generated|stock)|"
    r"and\s+then\s+(a\s+)?(cinematic|generated|ai|b-?roll)|"
    r"hybrid|mix(ed)?\s+with\s+(ai|generated|cinematic)|"
    r"after\s+(the\s+)?(tour|recording|demo).{0,40}(cinematic|generated|ai\s+scene)"
    r")\b",
    re.I,
)

_LIVE_VERB_RE = re.compile(
    r"\b("
    r"screen\s*record|record\s+(the\s+)?(screen|site|website|app|demo)|"
    r"walk\s*through|live\s+tour|product\s+tour|demo\s+of|"
    r"open\s+(the\s+)?(site|app|website)|go\s+to\s+(the\s+)?(site|website)"
    r")\b",
    re.I,
)

# Brand keys that are also live platforms (must never expand to Pexels B-roll)
_PLATFORM_ENTITIES = frozenset(
    {
        "cryptorafts",
        "huggingface",
        "chatgpt",
        "cursor",
        "github",
        "gemini",
        "google",
        "youtube",
    }
)


@dataclass(frozen=True)
class VideoRoute:
    """Immutable routing decision for one user ask."""

    pipeline: PipelineKind
    prefer_platform_record: bool
    hard_lock_live: bool
    platform: dict[str, Any] | None = None
    reasons: tuple[str, ...] = field(default_factory=tuple)
    original: str = ""

    @property
    def platform_id(self) -> str:
        if not self.platform:
            return ""
        return str(self.platform.get("id") or "")


def _resolve_platform(text: str) -> dict[str, Any] | None:
    """Same resolution order as today's hard-lock: built-in platforms, then web products."""
    t = (text or "").strip()
    if not t:
        return None
    try:
        from jarvis.mira.platforms import detect_platform

        plat = detect_platform(t)
        if plat:
            return plat
    except Exception:
        pass
    try:
        from jarvis.mira.web_products import looks_like_web_product_ask, resolve_web_product

        if looks_like_web_product_ask(t):
            return resolve_web_product(t)
    except Exception:
        pass
    return None


def _entity_forces_live(text: str) -> bool:
    try:
        from jarvis.mira.intent import detect_entity

        return detect_entity(text) in _PLATFORM_ENTITIES
    except Exception:
        return False


def _has_creative_extra(text: str) -> bool:
    return bool(_CREATIVE_EXTRA_RE.search(text or ""))


def _has_live_verb(text: str) -> bool:
    return bool(_LIVE_VERB_RE.search(text or ""))


def _has_product_signal(text: str) -> bool:
    try:
        from jarvis.mira.web_products import _PRODUCT_SIGNAL_RE

        return bool(_PRODUCT_SIGNAL_RE.search(text or ""))
    except Exception:
        return bool(
            re.search(
                r"\b(api\s*keys?|docs?|dashboard|console|saas|login|pricing|sdk)\b",
                text or "",
                re.I,
            )
        )


def route_video_ask(*texts: str) -> VideoRoute:
    """Decide live_screen | creative_generative | hybrid for a Mira video ask.

    Product / platform / SaaS / API asks → live_screen (hard-locked).
    Pure creative / lifestyle → creative_generative (existing stock/AI collage today).
    Live product + cinematic/generated extras → hybrid (still hard-locks live for now;
    generative half is a future provider — not implemented in Phase 1).
    """
    parts = [re.sub(r"\s+", " ", (t or "").strip()) for t in texts if (t or "").strip()]
    blob = " ".join(dict.fromkeys(parts))  # stable de-dupe, preserve order
    if not blob:
        return VideoRoute(
            pipeline="creative_generative",
            prefer_platform_record=False,
            hard_lock_live=False,
            platform=None,
            reasons=("empty_ask",),
            original="",
        )

    reasons: list[str] = []
    plat: dict[str, Any] | None = None
    for t in parts or [blob]:
        plat = _resolve_platform(t)
        if plat:
            reasons.append(f"platform:{plat.get('id')}")
            break
    if not plat:
        plat = _resolve_platform(blob)
        if plat:
            reasons.append(f"platform:{plat.get('id')}")

    entity_live = _entity_forces_live(blob) or any(_entity_forces_live(t) for t in parts)
    if entity_live:
        reasons.append("platform_entity")
        if not plat:
            for t in parts or [blob]:
                plat = _resolve_platform(t) or plat

    creative_extra = _has_creative_extra(blob)
    if creative_extra:
        reasons.append("creative_extra")

    product_signal = _has_product_signal(blob)
    live_verb = _has_live_verb(blob)
    if live_verb:
        reasons.append("live_verb")

    # Brand-guess alone must not steal pure creative asks
    # (e.g. "AI robot in a futuristic office" must stay creative_generative).
    # Catalog web products (_dynamic but not _guessed) still hard-lock live.
    if (
        plat
        and plat.get("_guessed")
        and creative_extra
        and not product_signal
        and not live_verb
        and not entity_live
    ):
        reasons.append("ignore_brand_guess_for_creative")
        plat = None

    live = bool(plat) or entity_live
    if live:
        reasons.append("live_product")

    if live and creative_extra:
        return VideoRoute(
            pipeline="hybrid",
            prefer_platform_record=True,
            hard_lock_live=True,
            platform=plat,
            reasons=tuple(reasons) + ("hybrid_live_plus_creative",),
            original=blob[:240],
        )

    if live:
        return VideoRoute(
            pipeline="live_screen",
            prefer_platform_record=True,
            hard_lock_live=True,
            platform=plat,
            reasons=tuple(reasons) or ("live_screen",),
            original=blob[:240],
        )

    return VideoRoute(
        pipeline="creative_generative",
        prefer_platform_record=False,
        hard_lock_live=False,
        platform=None,
        reasons=("creative_generative",) + tuple(reasons),
        original=blob[:240],
    )


def requires_live_hard_lock(route: VideoRoute | None) -> bool:
    """True when stock/AI fallback is forbidden (live or hybrid with product)."""
    if route is None:
        return False
    return bool(route.hard_lock_live)


def prefer_platform_record(route: VideoRoute | None) -> bool:
    if route is None:
        return False
    return bool(route.prefer_platform_record)
