"""Viral Shorts packaging — hooks, titles, descriptions for CTR + retention.

Uses LLM when available; always falls back to strong templates.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_PACK_SYSTEM = """You write YouTube Shorts packaging for maximum CTR + watch time.
Return ONLY valid JSON (no markdown):
{
  "hook": "max 36 chars on-screen text, curiosity, no hashtags",
  "title": "max 70 chars, curiosity hook, no spam emojis",
  "description": "2-4 short lines + soft CTA to comment/follow",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
  "mood": "one of: motivational|funny|calm|epic|curious|romantic|chill"
}
Rules:
- Stay EXACTLY on the user's topic — never invent a different subject
- Hook must make people watch the first 2 seconds
- Title should create open loops (Wait for it / Nobody talks about / POV)
- No URLs, no fake claims, no ALL CAPS spam
"""


def _clean_topic(topic: str) -> str:
    t = re.sub(r"\s+", " ", (topic or "").strip())
    t = re.sub(
        r"\b(upload|post|publish|to\s+youtube|youtube\s+shorts?|shorts?|please|for\s+me|"
        r"viral|growth|schedule|every\s+\d+\s*hours?)\b",
        " ",
        t,
        flags=re.I,
    )
    return re.sub(r"\s+", " ", t).strip(" .,:;-") or "This Short"


def _safe_drawtext(text: str, limit: int = 36) -> str:
    t = re.sub(r"[^A-Za-z0-9 .!?_\-]", "", (text or "").strip())
    t = re.sub(r"\s+", " ", t).strip()
    return t[:limit].rstrip(" .")


def _template_pack(topic: str) -> dict[str, Any]:
    clean = _clean_topic(topic)
    short = clean[:34]
    nouns = [w for w in re.findall(r"[A-Za-z]{3,}", clean) if w.lower() not in {
        "the", "and", "for", "with", "about", "this", "that", "from", "into", "your",
    }][:3]
    core = " ".join(nouns) if nouns else short

    hooks = [
        f"Wait for it — {short}",
        f"Nobody talks about {core}",
        f"POV: {short}",
        f"Watch till the end",
        f"{core} hits different",
    ]
    titles = [
        f"You won't believe this: {clean}",
        f"Wait for it… {clean}",
        f"Nobody talks about {clean}",
        f"POV: {clean}",
        f"{clean} (save this)",
        f"This {core} tip changes everything",
    ]
    idx = sum(ord(c) for c in clean) % len(titles)
    hook = _safe_drawtext(hooks[idx % len(hooks)], 36)
    title = titles[idx][:70].rstrip()
    if "#shorts" not in title.lower():
        title = f"{title} #Shorts"
    title = title[:95]

    tags = ["shorts", "viral", "fyp", "youtubeshorts"]
    for n in nouns[:3]:
        tags.append(n.lower())
    # soft niche tags
    lower = clean.lower()
    if any(k in lower for k in ("coffee", "tea", "food", "cook", "recipe")):
        tags += ["foodtok", "coffee"]
    if any(k in lower for k in ("money", "business", "hustle", "ai", "code")):
        tags += ["productivity", "mindset"]
    if any(k in lower for k in ("gym", "fitness", "workout", "health")):
        tags += ["fitness", "motivation"]
    tags = list(dict.fromkeys(tags))[:12]

    mood = "curious"
    if any(k in lower for k in ("funny", "joke", "laugh", "meme")):
        mood = "funny"
    elif any(k in lower for k in ("calm", "sleep", "rain", "nature", "ocean")):
        mood = "calm"
    elif any(k in lower for k in ("epic", "power", "hustle", "gym", "motivat")):
        mood = "motivational"
    elif any(k in lower for k in ("love", "romantic", "couple")):
        mood = "romantic"

    desc = (
        f"{clean}\n\n"
        "Watch till the end — it hits different.\n"
        "Like + follow for daily Shorts.\n"
        "Comment YT if you want the full automation.\n\n"
        "#Shorts #YouTubeShorts #Viral #FYP"
    )
    return {
        "hook": hook or "Watch till the end",
        "title": title,
        "description": desc[:4800],
        "tags": tags,
        "mood": mood,
    }


def pack_short(topic: str) -> dict[str, Any]:
    """Best available packaging for a Shorts topic."""
    clean = _clean_topic(topic)
    fallback = _template_pack(clean)
    try:
        from jarvis.mira.director import _llm_json

        planned = _llm_json(
            _PACK_SYSTEM,
            f"Topic: {clean}\nMake hook/title/description that stay on THIS topic.",
            timeout=8.0,
        )
        if not isinstance(planned, dict):
            return fallback
        hook = _safe_drawtext(str(planned.get("hook") or fallback["hook"]), 36)
        title = re.sub(r"\s+", " ", str(planned.get("title") or fallback["title"])).strip()[:70]
        if "#shorts" not in title.lower():
            title = f"{title} #Shorts"
        title = title[:95]
        desc = str(planned.get("description") or fallback["description"]).strip()
        if "comment" not in desc.lower() and "follow" not in desc.lower():
            desc = desc.rstrip() + "\n\nComment YT if you want the full automation."
        if "#shorts" not in desc.lower():
            desc = desc.rstrip() + "\n\n#Shorts #YouTubeShorts #Viral #FYP"
        tags = planned.get("tags") if isinstance(planned.get("tags"), list) else fallback["tags"]
        tags = [str(t).strip().lstrip("#")[:32] for t in tags if str(t).strip()][:12] or fallback["tags"]
        mood = str(planned.get("mood") or fallback["mood"]).strip().lower() or fallback["mood"]
        return {
            "hook": hook or fallback["hook"],
            "title": title,
            "description": desc[:4800],
            "tags": tags,
            "mood": mood,
        }
    except Exception as exc:
        logger.debug("pack_short LLM skipped: %s", exc)
        return fallback


def viral_hook_line(topic: str) -> str:
    return str(pack_short(topic).get("hook") or "Watch till the end")


def viral_title_description(topic: str) -> tuple[str, str]:
    p = pack_short(topic)
    return str(p["title"]), str(p["description"])


def viral_tags(topic: str) -> list[str]:
    return list(pack_short(topic).get("tags") or ["shorts", "viral"])


def viral_mood(topic: str) -> str:
    return str(pack_short(topic).get("mood") or "curious")
