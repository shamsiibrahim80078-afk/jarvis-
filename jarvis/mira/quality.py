"""Audience-oriented prompts + lightweight learning from ratings (not NN weights)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_CONFIG_DIR = Path(__file__).resolve().parent
_ENGINE_CONFIG = _CONFIG_DIR / "config.json"
_LEARNING_CONFIG = _CONFIG_DIR / "learning_config.json"
_DATA_LEARNING = Path(__file__).resolve().parents[2] / "data" / "mira" / "learning_config.json"

_STOP = frozenset(
    {
        "a", "an", "the", "and", "or", "of", "to", "for", "in", "on", "with",
        "is", "are", "be", "as", "at", "by", "from", "this", "that", "it",
        "my", "your", "our", "make", "create", "generate", "image", "video",
        "please", "want", "need", "me",
    }
)

_DEFAULT_ANCHOR = (
    "ultra detailed photoreal cinematic still, sharp focus, volumetric light, "
    "film color grade, shallow depth of field, coherent single subject, "
    "no watermark, no text, no logo"
)

_DEFAULT_NEGATIVE = (
    "blurry, watermark, text, logo, deformed, extra limbs, low quality, "
    "oversaturated neon spam, collage, UI overlay"
)


def load_engine_config() -> dict[str, Any]:
    try:
        data = json.loads(_ENGINE_CONFIG.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _learning_path() -> Path:
    if _DATA_LEARNING.is_file():
        return _DATA_LEARNING
    return _LEARNING_CONFIG


def load_learning_config() -> dict[str, Any]:
    path = _learning_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {
            "preferred_styles": ["cinematic"],
            "negative_from_downvotes": [],
            "prompt_suffixes_from_upvotes": [],
            "rated_examples": 0,
        }


def save_learning_config(cfg: dict[str, Any]) -> Path:
    out = Path(__file__).resolve().parents[2] / "data" / "mira" / "learning_config.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    cfg = dict(cfg)
    cfg["updated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    out.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {w for w in words if len(w) > 2 and w not in _STOP}


def enhance_still_prompt(user_text: str, *, style: str = "cinematic", shot: str = "") -> str:
    """Subject-first prompt — quality words after the topic, not drowning it."""
    base = re.sub(r"\s+", " ", (user_text or "").strip())
    if not base:
        base = "cinematic scene"
    cfg = load_engine_config()
    anchor = str(cfg.get("quality_anchor") or _DEFAULT_ANCHOR)
    negative = str(cfg.get("negative") or _DEFAULT_NEGATIVE)
    learn = load_learning_config()

    # Keep subject dominant; append style + shot + quality
    parts = [base]
    if style and style.lower() not in base.lower():
        parts.append(f"{style} photography")
    if shot:
        parts.append(shot)
    # Software / API / docs asks must NEVER become fashion portraits
    if re.search(
        r"\b(api|sdk|docs?|key|token|dashboard|console|login|saas|software|"
        r"website|app|platform|developer|code|endpoint)\b",
        base,
        re.I,
    ):
        parts.append("product UI screenshot style, computer screen, interface, documentation page")
        parts.append(
            "negative: human portrait, fashion model, woman face, man face, "
            "beauty shot, influencer selfie, random person"
        )
    parts.append(anchor)
    parts.append(f"negative: {negative}")

    for suf in (learn.get("prompt_suffixes_from_upvotes") or [])[:1]:
        if isinstance(suf, str) and suf.strip() and keyword_overlap_score(base, suf) >= 0.25:
            parts.append(suf.strip()[:120])

    out = ", ".join(p for p in parts if p)
    return out[:1600]


def keyword_overlap_score(a: str, b: str) -> float:
    ta, tb = tokenize(a), tokenize(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(1, len(ta | tb))


def audience_script(topic: str, *, seconds: int = 30) -> str:
    """VO that matches the actual topic — not generic coach spam."""
    t = re.sub(r"\s+", " ", (topic or "this scene").strip()) or "this scene"
    if seconds <= 20:
        return (
            f"Look closely — {t}. "
            f"Every detail in this moment tells a story. Stay with it."
        )
    if seconds <= 40:
        return (
            f"This is {t}. "
            f"Feel the atmosphere, the light, the motion. "
            f"A single clear picture — cinematic, sharp, unforgettable."
        )
    return (
        f"Tonight we look at {t}. "
        f"From the wide establishing frame, into the detail, then the hero moment. "
        f"Built for the screen — clean, vivid, and hard to look away from."
    )


def shot_angles(n: int) -> list[str]:
    """Cinematic shot list — same subject, different cameras."""
    templates = [
        "wide establishing shot, epic scale, rule of thirds, deep background",
        "medium shot, eye level, subject clearly centered, cinematic framing",
        "close-up detail, shallow depth of field, tack-sharp focus on subject",
        "low-angle hero shot, dramatic sky or ceiling, powerful presence",
        "tracking-style three-quarter view, dynamic side light, rich atmosphere",
        "final wide pull-back, emotional closing frame, soft bokeh edges",
    ]
    n = max(1, min(8, int(n or 5)))
    return [templates[i % len(templates)] for i in range(n)]


def rebuild_from_feedback(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Recompute learning adapter from rating rows (1-5 or thumbs)."""
    from collections import Counter

    ups = [r for r in rows if int(r.get("rating") or 0) >= 4]
    downs = [r for r in rows if int(r.get("rating") or 0) <= 2]
    style_counts: Counter[str] = Counter()
    suffixes: list[str] = []
    for row in ups:
        st = (row.get("style") or "").strip().lower()
        if st:
            style_counts[st] += 1
        prompt = (row.get("prompt") or "").strip()
        if prompt and len(prompt) > 24:
            suffixes.append(prompt[-160:].strip())
        topic = (row.get("topic") or "").strip()
        if topic and len(topic) > 8:
            suffixes.append(f"quality look inspired by past success: {topic[:100]}")

    neg_bits: list[str] = []
    for row in downs:
        blob = f"{row.get('topic') or ''} {row.get('prompt') or ''}".lower()
        for t in list(tokenize(blob))[:6]:
            phrase = f"avoid failed look: {t}"
            if phrase not in neg_bits:
                neg_bits.append(phrase)

    cfg = {
        "version": 1,
        "kind": "mira_learning_adapter",
        "disclaimer": "Learns from your ratings in Jarvis. Not foundation-model training.",
        "preferred_styles": [s for s, _ in style_counts.most_common(5)] or ["cinematic"],
        "negative_from_downvotes": neg_bits[:12],
        "prompt_suffixes_from_upvotes": suffixes[:8],
        "rated_examples": len(rows),
    }
    save_learning_config(cfg)
    return cfg
