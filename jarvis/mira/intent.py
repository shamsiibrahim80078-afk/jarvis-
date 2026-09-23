"""Expand thin user asks into visual intent — like other video models.

"google" must mean Google search / product / brand scenes — NOT wooden letter stamps.
"""

from __future__ import annotations

import re
from typing import Any

# Brand / entity → real visual scenes (search + still prompts)
_ENTITY_SCENES: dict[str, dict[str, Any]] = {
    "google": {
        "visual_brief": (
            "person using Google search on a laptop screen, Google homepage visible, "
            "modern desk, natural light, photoreal cinematic"
        ),
        "queries": [
            "google search laptop screen",
            "typing on google search",
            "smartphone google app",
            "google logo screen close up",
            "person browsing google chrome",
        ],
        "prefer_ai_stills": True,
        "reject": r"wooden|alphabet|letter.?block|rubber.?stamp|scrabble|tile.?letter|typo.?block|stamps?",
        # Stock alt often omits brand name — these scene words count as on-brief
        "scene_ok": (
            "laptop", "computer", "smartphone", "phone", "chrome", "search",
            "browser", "keyboard", "typing", "screen", "monitor", "homepage",
        ),
    },
    "youtube": {
        "visual_brief": "person watching YouTube on phone or laptop, YouTube play button on screen, cinematic",
        "queries": ["youtube on phone screen", "watching youtube laptop", "youtube play button"],
        "prefer_ai_stills": True,
        "reject": r"wooden|alphabet|letter.?block|scrabble|stamp",
        "scene_ok": ("phone", "laptop", "play", "streaming", "watching", "screen"),
    },
    "facebook": {
        "visual_brief": "person scrolling Facebook on smartphone, Facebook app interface, lifestyle cinematic",
        "queries": ["facebook app phone", "scrolling social media phone", "facebook logo screen"],
        "prefer_ai_stills": True,
        "reject": r"wooden|alphabet|letter.?block|scrabble|stamp",
        "scene_ok": ("phone", "smartphone", "scrolling", "social", "app", "feed"),
    },
    "instagram": {
        "visual_brief": "person using Instagram on phone, camera and feed lifestyle, colorful cinematic",
        "queries": ["instagram phone scroll", "taking photo for instagram", "instagram app screen"],
        "prefer_ai_stills": True,
        "reject": r"wooden|alphabet|letter.?block|scrabble|stamp",
        "scene_ok": ("phone", "camera", "photo", "selfie", "feed", "social"),
    },
    "tiktok": {
        "visual_brief": "person watching TikTok on phone vertical screen, modern lifestyle cinematic",
        "queries": ["tiktok phone vertical", "scrolling tiktok phone", "phone social video"],
        "prefer_ai_stills": True,
        "reject": r"wooden|alphabet|letter.?block|scrabble|stamp",
        "scene_ok": ("phone", "vertical", "scrolling", "social", "video"),
    },
    "apple": {
        "visual_brief": "Apple iPhone or MacBook product cinematic close up, clean studio light",
        "queries": ["iphone close up cinematic", "macbook desk lifestyle", "apple store product"],
        "prefer_ai_stills": True,
        "reject": r"wooden|alphabet|fruit.?apple.?pile|orchard",
        "scene_ok": ("iphone", "macbook", "ipad", "airpods", "macos", "ios"),
    },
    "microsoft": {
        "visual_brief": "Windows laptop Microsoft Office screen, modern office cinematic",
        "queries": ["windows laptop screen", "microsoft office computer", "surface laptop desk"],
        "prefer_ai_stills": True,
        "reject": r"wooden|alphabet|letter.?block",
        "scene_ok": ("windows", "laptop", "office", "surface", "computer"),
    },
    "amazon": {
        "visual_brief": "Amazon package delivery, online shopping on phone, cardboard box cinematic",
        "queries": ["amazon package delivery", "online shopping phone", "cardboard shipping box"],
        "prefer_ai_stills": False,
        "reject": r"wooden|alphabet|letter.?block|rainforest",
        "scene_ok": ("package", "delivery", "box", "shipping", "shopping", "parcel"),
    },
    "netflix": {
        "visual_brief": "watching Netflix on TV living room night, streaming screen glow cinematic",
        "queries": ["watching netflix tv", "streaming movie couch", "tv screen living room night"],
        "prefer_ai_stills": True,
        "reject": r"wooden|alphabet|letter.?block",
        "scene_ok": ("tv", "television", "streaming", "couch", "movie", "living"),
    },
    "chatgpt": {
        "visual_brief": "ChatGPT AI chat on laptop screen, modern desk, blue UI glow, cinematic",
        "queries": ["ai chatbot laptop screen", "person typing ai chat", "openai chatgpt screen"],
        "prefer_ai_stills": True,
        "reject": r"wooden|alphabet|letter.?block",
        "scene_ok": ("laptop", "chat", "ai", "openai", "screen", "typing"),
    },
    "huggingface": {
        "visual_brief": "Hugging Face website models and spaces on a laptop screen, AI hub cinematic",
        "queries": ["hugging face website", "ai model hub laptop", "machine learning website screen"],
        "prefer_ai_stills": True,
        "reject": r"wooden|alphabet|letter.?block|scrabble|stamp",
        "scene_ok": ("model", "dataset", "laptop", "screen", "ai", "machine"),
    },
    "cursor": {
        "visual_brief": "Cursor AI code editor on a computer screen, dark IDE cinematic",
        "queries": ["code editor screen dark", "ai coding ide laptop", "software developer ide"],
        "prefer_ai_stills": True,
        "reject": r"wooden|alphabet|letter.?block|mouse\s+cursor\s+only",
        "scene_ok": ("code", "editor", "ide", "laptop", "screen", "programming"),
    },
    "github": {
        "visual_brief": "GitHub website repositories on laptop screen, developer cinematic",
        "queries": ["github website laptop", "code repository screen", "git pull request"],
        "prefer_ai_stills": True,
        "reject": r"wooden|alphabet|letter.?block",
        "scene_ok": ("repository", "code", "laptop", "screen", "commit", "developer"),
    },
    "cryptorafts": {
        "visual_brief": "CryptoRafts Web3 platform on laptop — founders, VCs, dealflow, BNB Chain",
        "queries": ["cryptocurrency trading laptop", "blockchain startup office", "web3 dashboard screen"],
        "prefer_ai_stills": True,
        "reject": r"wooden|alphabet|letter.?block|scrabble|stamp",
        "scene_ok": ("crypto", "blockchain", "trading", "dashboard", "laptop", "web3"),
    },
    "gemini": {
        "visual_brief": "Google Gemini AI chat on laptop screen, modern product UI cinematic",
        "queries": ["google gemini ai chat laptop", "ai assistant chatbot screen", "gemini google product"],
        "prefer_ai_stills": True,
        "reject": r"wooden|alphabet|letter.?block|scrabble|stamp",
        "scene_ok": ("gemini", "chat", "assistant", "google", "laptop", "ai"),
    },
    "ai": {
        "visual_brief": "artificial intelligence neural network visualization, futuristic tech cinematic",
        "queries": ["artificial intelligence visualization", "neural network abstract", "futuristic ai tech"],
        "prefer_ai_stills": True,
        "reject": r"wooden|alphabet|letter.?block",
        "scene_ok": ("neural", "robot", "futuristic", "technology", "circuit", "intelligence"),
    },
}

# Always junk for product/brand asks (letter toys that "spell" the word)
_GLOBAL_JUNK = re.compile(
    r"\b(wooden\s+letter|alphabet\s+block|letter\s+stamp|rubber\s+stamp|"
    r"scrabble|tile\s+letter|typo\s+block|letterpress|wooden\s+block|"
    r"spelling\s+with\s+letters|toy\s+letters)\b",
    re.I,
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def detect_entity(text: str) -> str | None:
    """Return known entity key if the ask is mainly that brand/product."""
    t = _norm(text)
    # Multi-word platforms before stripping chrome words
    if re.search(r"\bhugging\s*face\b|\bhuggingface\b", t):
        return "huggingface"
    if re.search(r"\bchat\s*gpt\b|\bchatgpt\b", t):
        return "chatgpt"
    if re.search(r"\bcrypto\s*rafts?\b|\bcryptorafts?\b", t):
        return "cryptorafts"
    if re.search(r"\b(google\s+)?gemini\b|\bgemini\.google\b", t):
        return "gemini"
    t = re.sub(
        r"\b(make|create|generate|produce|shoot|render|video|clip|reel|short|"
        r"shorts|mute|silent|about|of|for|on|a|an|the|please|want|need)\b",
        " ",
        t,
    )
    t = re.sub(r"\s+", " ", t).strip()
    words = t.split()
    if not words:
        return None
    # Exact / dominant entity (longer keys first)
    for key in sorted(_ENTITY_SCENES.keys(), key=len, reverse=True):
        if re.search(rf"\b{re.escape(key)}\b", t):
            return key
    return None


def entity_scene_tokens(entity: str | None) -> tuple[str, ...]:
    """Scene words that count as on-brief for a brand when alt omits the brand name."""
    if not entity or entity not in _ENTITY_SCENES:
        return ()
    return tuple(_ENTITY_SCENES[entity].get("scene_ok") or ())


def is_junk_stock_meta(meta: str, *, entity: str | None = None) -> bool:
    """True when stock is letter-toys / typography junk, not a real scene."""
    m = meta or ""
    if _GLOBAL_JUNK.search(m):
        return True
    if entity and entity in _ENTITY_SCENES:
        pat = _ENTITY_SCENES[entity].get("reject")
        if pat and re.search(pat, m, re.I):
            return True
    return False


def expand_ask(text: str) -> dict[str, Any]:
    """
    Turn a raw user ask into visual intent.

    Returns:
      brief: expanded visual description for prompts / VO context
      search_queries: Pexels-friendly scene queries
      prefer_ai_stills: skip literal stock photos that spell the word
      prefer_platform_record: open real site and screen-record when known
      entity: brand key if any
      original: cleaned original topic
    """
    raw = (text or "").strip()
    original = re.sub(
        r"^(?:mira[,:]?\s*)?(?:please\s+)?(?:make|create|generate)\s+"
        r"(?:me\s+)?(?:an?\s+)?(?:mute\s+|silent\s+)?(?:video|clip|short|shorts|reel)\s+"
        r"(?:about|of|on|for)?\s*",
        "",
        raw,
        flags=re.I,
    ).strip() or raw
    original = re.sub(r"\s+", " ", original).strip(" .,:;-") or raw[:80]

    # Single routing boundary (live / creative / hybrid) — hard-lock behavior unchanged
    prefer_platform = False
    video_pipeline = "creative_generative"
    try:
        from jarvis.mira.video_router import route_video_ask

        _route = route_video_ask(raw, original)
        prefer_platform = bool(_route.prefer_platform_record)
        video_pipeline = str(_route.pipeline)
    except Exception:
        prefer_platform = False
        video_pipeline = "creative_generative"

    entity = detect_entity(original) or detect_entity(raw)
    # Brand keys that are also live platforms — never expand to Pexels/AI B-roll
    _PLATFORM_ENTITIES = {
        "cryptorafts",
        "huggingface",
        "chatgpt",
        "cursor",
        "github",
        "gemini",
        "google",
        "youtube",
    }
    if entity in _PLATFORM_ENTITIES:
        prefer_platform = True
        if video_pipeline == "creative_generative":
            video_pipeline = "live_screen"

    if entity and entity in _ENTITY_SCENES:
        meta = _ENTITY_SCENES[entity]
        # Platform entities: keep the real product ask — never swap to stock "laptop" B-roll brief
        if prefer_platform:
            return {
                "original": original,
                "entity": entity,
                "brief": original,
                "search_queries": [original[:80]],
                "prefer_ai_stills": False,
                "prefer_platform_record": True,
                "video_pipeline": video_pipeline if video_pipeline != "creative_generative" else "live_screen",
                "reject_pattern": str(meta.get("reject") or ""),
                "_via": "platform_exact",
            }
        return {
            "original": original,
            "entity": entity,
            "brief": str(meta["visual_brief"]),
            "search_queries": list(meta["queries"])[:6],
            "prefer_ai_stills": bool(meta.get("prefer_ai_stills")),
            "prefer_platform_record": prefer_platform,
            "video_pipeline": video_pipeline,
            "reject_pattern": str(meta.get("reject") or ""),
            "_via": "entity_expand",
        }

    # Thin 1–2 word topics → force cinematic scene phrasing for AI/stock
    # BUT never for live product/site asks (those must stay on-brief)
    words = [w for w in re.findall(r"[a-zA-Z0-9]+", original.lower()) if len(w) > 1]
    if prefer_platform:
        return {
            "original": original,
            "entity": entity,
            "brief": original,
            "search_queries": [original[:80]],
            "prefer_ai_stills": False,
            "prefer_platform_record": True,
            "video_pipeline": video_pipeline if video_pipeline != "creative_generative" else "live_screen",
            "reject_pattern": "",
            "_via": "platform_or_web_product",
        }
    if 1 <= len(words) <= 2:
        core = " ".join(words)
        return {
            "original": original,
            "entity": None,
            "brief": (
                f"cinematic photoreal video of {core}, clear subject, "
                f"real world scene, professional lighting, no text overlays, no letter toys"
            ),
            "search_queries": [
                core,
                f"{core} cinematic",
                f"{core} close up",
                f"person with {core}" if len(words) == 1 else f"{core} lifestyle",
            ],
            "prefer_ai_stills": len(words) == 1,
            "prefer_platform_record": prefer_platform,
            "video_pipeline": video_pipeline,
            "reject_pattern": r"wooden|alphabet|letter.?block|scrabble|stamp",
            "_via": "thin_topic_expand",
        }

    return {
        "original": original,
        "entity": None,
        "brief": original,
        "search_queries": [original[:80]],
        "prefer_ai_stills": False,
        "prefer_platform_record": prefer_platform,
        "video_pipeline": video_pipeline,
        "reject_pattern": "",
        "_via": "passthrough",
    }
