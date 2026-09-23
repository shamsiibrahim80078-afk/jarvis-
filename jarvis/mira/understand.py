"""Understand ANY natural-language video/image ask — like GPT, not a prompt whitelist.

Random users will say messy things:
  "yo can u do that thing with dogs on a beach"
  "i need something cool about cooking pasta"
  "fruits that talk to each other"
  "show me tokyo at night"

This module turns that into a clear brief Mira can shoot.
"""

from __future__ import annotations

import re
from typing import Any

_UNDERSTAND_SYSTEM = """You extract creative media intent from casual user messages.
The user may speak messily, with slang, typos, or no special "prompt format".
Act like GPT: understand what they WANT visually, even if wording is imperfect.

Return ONLY valid JSON (no markdown):
{
  "wants_media": true,
  "media": "video",
  "brief": "clear concrete subject to film — preserve their idea exactly",
  "search_queries": ["3-6 word stock search 1", "search 2", "search 3"],
  "audio_mode": "voice",
  "use_uploads": false,
  "duration_sec": 30,
  "aspect": "16:9",
  "character_dialogue": false,
  "confidence": 0.0
}

Rules:
- wants_media=true if they want you to MAKE / CREATE / SHOW / SHOOT / EDIT a video/image/clip/reel
- wants_media=false for chat questions, YouTube search, opening apps, weather, etc.
- brief MUST be their idea in plain words — keep THEIR nouns/verbs (not "cinematic scene", not office unless they asked)
- Strip only chrome words (upload/youtube/viral/shorts) — keep the creative subject EXACTLY
- search_queries: concrete Pexels-friendly phrases that NAME the user's subjects (never office/AI/coding filler)
- audio_mode: voice|ambient|both|mute
- character_dialogue=true only if subjects talk/converse (fruits talking, cats arguing, etc.)
- media: video or image (default video)
- If unclear but creative, prefer wants_media=true and best-guess brief from their words
- Never invent a different topic than what they said — fidelity over creativity
"""


def _heuristic_understand(text: str) -> dict[str, Any]:
    """Offline fallback — still open to ANY topic words, not a fixed list."""
    raw = re.sub(r"\s+", " ", (text or "").strip())
    lower = raw.lower()

    # Hard non-media (do NOT treat "make a video about google" as web-search)
    web_searchish = bool(
        re.search(
            r"\b(youtube|on yt|open (chrome|spotify|notepad)|what('?s| is) the (time|weather)|"
            r"search the web|volume (up|down)|shutdown|restart pc)\b",
            lower,
        )
    )
    # Bare "google X" without make/video = web search; "video about google" = Mira
    bare_google_search = bool(
        re.search(r"\bgoogle\b", lower)
        and not re.search(r"\b(make|create|generate|render|produce|video|clip|short|reel|image)\b", lower)
    )
    if (web_searchish or bare_google_search) and not re.search(
        r"\b(make|create|generate|render|produce)\b", lower
    ):
        return {
            "wants_media": False,
            "media": "video",
            "brief": "",
            "search_queries": [],
            "audio_mode": "voice",
            "use_uploads": False,
            "duration_sec": 30,
            "aspect": "16:9",
            "character_dialogue": False,
            "confidence": 0.9,
            "_via": "heuristic_reject",
        }

    genish = bool(
        re.search(
            r"\b(make|create|generate|render|produce|shoot|film|edit|build|craft|"
            r"compose|show\s+me|put\s+together|whip\s+up|cook\s+up|do\s+me|"
            r"can\s+(?:you|u)|could\s+(?:you|u)|please|pls|i\s+want|i\s+need|"
            r"i'?d\s+like|wanna|gimme|give\s+me|mira|do\s+that|do\s+something)\b",
            lower,
        )
    )
    media_noun = bool(
        re.search(
            r"\b(video|clip|reel|shorts?|film|movie|montage|image|picture|photo|"
            r"still|animation|footage|visual|content)\b",
            lower,
        )
    )
    # Soft creative: describes a scene without saying "video"
    sceneish = bool(
        re.search(
            r"\b(talking|talk|speak|speaking|dancing|running|flying|cooking|diving|"
            r"sunset|beach|city|forest|space|robot|dragon|cat|cats|dog|dogs|"
            r"fruit|fruits|car|ocean|about|showing|featuring)\b",
            lower,
        )
    ) and genish

    wants = bool(genish and (media_noun or sceneish or "mira" in lower))
    if not wants and media_noun and re.search(r"\b(about|of|on|for)\b", lower):
        wants = True
    # Dialogue subjects without "make a video" still count
    if not wants and re.search(r"\b(talk|talking|speak|speaking|argue|arguing)\b", lower):
        if re.search(
            r"\b(fruit|fruits|cat|cats|dog|dogs|animal|toy|robot|dragon|character)\b",
            lower,
        ):
            wants = True

    media = "image" if (
        re.search(r"\b(image|picture|photo|still)\b", lower)
        and not re.search(r"\b(video|clip|reel|film|movie|montage)\b", lower)
    ) else "video"

    brief = raw
    # Strip command chrome only
    brief = re.sub(
        r"^(?:mira[,:]?\s*)?(?:please\s+)?(?:hey\s+)?(?:yo\s+)?"
        r"(?:can\s+(?:you|u)|could\s+(?:you|u)|would\s+(?:you|u))?\s*"
        r"(?:please\s+|pls\s+)?(?:just\s+)?",
        "",
        brief,
        flags=re.I,
    )
    brief = re.sub(
        r"^(?:i\s+(?:want|need)|i'?d\s+like|wanna|gimme|give\s+me|do\s+me|"
        r"show\s+me|put\s+together|whip\s+up|cook\s+up)\s+",
        "",
        brief,
        flags=re.I,
    )
    brief = re.sub(
        r"^(?:do\s+(?:me\s+)?(?:that\s+)?(?:thing|one|something)\s+(?:with|about|of)\s+)",
        "",
        brief,
        flags=re.I,
    )
    brief = re.sub(
        r"^(?:to\s+)?(?:make|create|generate|render|produce|shoot|film|edit|build|"
        r"craft|compose)\s+(?:me\s+)?(?:an?\s+)?(?:ai\s+)?",
        "",
        brief,
        flags=re.I,
    )
    brief = re.sub(r"^\d+\s*(?:s|sec|secs|seconds)\s+", "", brief, flags=re.I)
    brief = re.sub(r"^(?:mute|silent|ambient)\s+", "", brief, flags=re.I)
    brief = re.sub(
        r"^(?:an?\s+)?(?:ai\s+)?(?:mute|silent)?\s*"
        r"(?:video|clip|reel|shorts?|film|movie|montage|"
        r"image|picture|photo|still|thing|one|something)\s*"
        r"(?:about|on|of|for|from|with|showing|featuring)?\s*",
        "",
        brief,
        flags=re.I,
    )
    brief = re.sub(
        r"\b(?:using|with|from)\s+my\s+uploads?\b|\b\d+\s*(?:s|sec|seconds)\b|"
        r"\b(?:vertical|9\s*:\s*16|16\s*:\s*9|no\s+voice|ambient\s+only|"
        r"mute|silent|no\s+audio|no\s+sound|music\s+only|bgm)\b|"
        r"\b(?:please|pls)\b$",
        "",
        brief,
        flags=re.I,
    )
    # Soft cleanup: "cool about cooking pasta" → "cooking pasta"
    brief = re.sub(r"^(?:cool|nice|awesome|sick|lit)\s+(?:about|of|with)\s+", "", brief, flags=re.I)
    brief = re.sub(r"\s+", " ", brief).strip(" .,:;-") or raw[:80]

    stop = {
        "the", "and", "for", "with", "that", "this", "from", "just", "like",
        "some", "cool", "nice", "really", "very", "thing", "something", "please",
        "video", "clip", "reel", "film", "movie", "make", "want", "need",
        "can", "you", "about", "each", "other", "them", "they",
        "second", "seconds", "mute", "silent", "short", "shorts", "music",
    }
    words = [w for w in re.findall(r"[a-zA-Z0-9]+", brief.lower()) if w not in stop and len(w) > 2]
    if not wants and genish and len(words) >= 2:
        wants = True
    core = " ".join(words[:5]) or brief[:40]
    queries = [
        core,
        f"{core} cinematic",
        f"{' '.join(words[:3])} close up" if words else core,
    ]

    audio = "voice"
    if re.search(r"\b(mute|silent|no\s+audio)\b", lower):
        audio = "mute"
    elif re.search(r"\b(no\s+voice|ambient|no\s+narration|with\s+music|music\s+only|bgm|just\s+music)\b", lower):
        audio = "ambient"
    elif re.search(r"\b(both|voice\s+and\s+ambient)\b", lower):
        audio = "both"

    uploads = bool(re.search(r"\b(my\s+uploads?|using\s+uploads?|uploaded)\b", lower))
    if not uploads:
        try:
            from jarvis.mira.uploads import should_use_uploads

            uploads = should_use_uploads(text)
        except Exception:
            pass
    aspect = "9:16" if re.search(r"\b(short|shorts|vertical|reel|tiktok|9\s*:\s*16)\b", lower) else "16:9"
    dur = 30
    dm = re.search(r"(\d+)\s*(?:s|sec|secs|seconds)\b", lower)
    if dm:
        try:
            dur = max(12, min(90, int(dm.group(1))))
        except ValueError:
            dur = 30

    dialogue = bool(
        re.search(r"\b(talking|talk|speak|speaking|conversation|argue|arguing|dialogue)\b", lower)
        and re.search(
            r"\b(fruit|fruits|cat|cats|dog|dogs|animal|toy|object|character|banana|"
            r"lemon|apple|robot|dragon)\b",
            lower,
        )
    )

    # Expand thin brands / entities into real visual scenes
    prefer_ai = False
    try:
        from jarvis.mira.intent import expand_ask

        ex = expand_ask(raw)
        if ex.get("_via") in ("entity_expand", "thin_topic_expand"):
            brief = str(ex.get("brief") or brief)
            expanded_q = [str(q) for q in (ex.get("search_queries") or []) if str(q).strip()]
            if expanded_q:
                queries = expanded_q + [q for q in queries if q not in expanded_q]
                queries = queries[:6]
            prefer_ai = bool(ex.get("prefer_ai_stills"))
    except Exception:
        pass

    return {
        "wants_media": wants,
        "media": media,
        "brief": brief,
        "search_queries": queries,
        "audio_mode": audio,
        "use_uploads": uploads,
        "duration_sec": dur,
        "aspect": aspect,
        "character_dialogue": dialogue,
        "prefer_ai_stills": prefer_ai,
        "confidence": 0.7 if wants else 0.4,
        "_via": "heuristic",
    }


def understand_ask(text: str) -> dict[str, Any]:
    """GPT-style understanding of any user media request."""
    raw = (text or "").strip()
    if not raw:
        return _heuristic_understand("")

    heur = _heuristic_understand(raw)

    # Skip LLM when heuristic is already clear (keeps chat snappy)
    brief0 = str(heur.get("brief") or "")
    messy = bool(
        re.search(r"\b(yo|u|pls|gimme|wanna|idk|lol|fr)\b", raw, re.I)
        or len(raw.split()) > 18
        or len(brief0.split()) < 2
        or "thing" in brief0.lower()
        or "something" in brief0.lower()
    )
    if heur.get("wants_media") and float(heur.get("confidence") or 0) >= 0.7 and not messy:
        return heur

    # Try LLM for messy / slang / incomplete phrasing
    try:
        from jarvis.mira.director import _llm_json

        planned = _llm_json(
            _UNDERSTAND_SYSTEM,
            f"User said (exact):\n{raw[:500]}\n\nExtract their media intent.",
            timeout=6.0,
        )
    except Exception:
        planned = None

    if not isinstance(planned, dict):
        return heur

    wants = planned.get("wants_media")
    if wants is None:
        wants = heur["wants_media"]
    brief = str(planned.get("brief") or heur.get("brief") or "").strip()
    if not brief or brief.lower() in ("cinematic scene", "video", "clip", "something"):
        brief = heur.get("brief") or raw[:120]

    queries = planned.get("search_queries")
    if not isinstance(queries, list) or len(queries) < 1:
        queries = heur.get("search_queries") or [brief]
    queries = [re.sub(r"\s+", " ", str(q).strip())[:80] for q in queries if str(q).strip()][:6]

    media = str(planned.get("media") or heur.get("media") or "video").lower()
    if media not in ("video", "image"):
        media = "video"

    audio = str(planned.get("audio_mode") or heur.get("audio_mode") or "voice").lower()
    if audio not in ("voice", "ambient", "both", "mute"):
        audio = "voice"

    try:
        dur = int(planned.get("duration_sec") or heur.get("duration_sec") or 30)
    except (TypeError, ValueError):
        dur = 30
    dur = max(12, min(90, dur))

    aspect = str(planned.get("aspect") or heur.get("aspect") or "16:9")
    if aspect not in ("16:9", "9:16"):
        aspect = "9:16" if "9" in aspect else "16:9"

    # Never let LLM invent office when user didn't ask
    blob = f"{brief} {' '.join(queries)}".lower()
    if "office" in blob and "office" not in raw.lower():
        brief = heur.get("brief") or brief
        queries = heur.get("search_queries") or queries

    conf = planned.get("confidence")
    try:
        conf_f = float(conf) if conf is not None else 0.8
    except (TypeError, ValueError):
        conf_f = 0.8

    # Uploads only when user explicitly asked — never let LLM reuse old media
    use_up = False
    try:
        from jarvis.mira.uploads import wants_user_media

        use_up = wants_user_media(text) or bool(heur.get("use_uploads"))
    except Exception:
        use_up = bool(heur.get("use_uploads"))

    return {
        "wants_media": bool(wants),
        "media": media,
        "brief": brief,
        "search_queries": queries,
        "audio_mode": audio,
        "use_uploads": use_up,
        "duration_sec": dur,
        "aspect": aspect,
        "character_dialogue": bool(
            planned.get("character_dialogue")
            if planned.get("character_dialogue") is not None
            else heur.get("character_dialogue")
        ),
        "confidence": conf_f,
        "_via": "llm+" + str(heur.get("_via") or "heuristic"),
    }
