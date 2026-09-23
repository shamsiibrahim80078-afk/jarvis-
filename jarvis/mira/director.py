"""Mira Creative Director — turns ANY user ask into a shootable video plan.

Not a trained video NN. This is the intelligence layer that makes Mira handle
coffee shops, deserts, product ads, travel vlogs, cooking, sports — whatever
the user says — by planning beats, Pexels queries, and VO like a director.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]

_DIRECTOR_SYSTEM = """You are Mira Creative Director for Jarvis — elite short-form video planner.
The user may speak casually, with slang, typos, or incomplete sentences — like talking to GPT.
Understand their INTENT and plan the EXACT idea they asked for.
Do not require a special prompt format. Do not substitute a different topic.
Do not default to office, tech, or corporate unless they asked for that.

Return ONLY valid JSON (no markdown) with this shape:
{
  "title": "short title matching the ask",
  "mood": "one mood word",
  "style": "cinematic|vlog|ad|documentary|reel|dialogue",
  "mode": "stock|character",
  "beats": [
    {
      "heading": "SHORT CAPS TITLE",
      "speaker": "optional character name for dialogue",
      "line": "spoken line max 16 words — for dialogue, first person as that character",
      "query": "3-7 word Pexels search ONLY if mode=stock",
      "still_prompt": "detailed image prompt if mode=character (anthropomorphic/talking subject)"
    }
  ]
}

Rules:
- beats length = requested N
- FIDELITY FIRST: plan ONLY what the user asked for. Same subjects, same setting, same vibe.
- Title and every beat heading/line/query must be about THAT idea — never invent a different topic.
- NEVER swap in office, AI agents, coding, YouTube, upload, or tech unless the user asked for those.
- If subjects are TALKING / conversing: mode MUST be "character", give each beat a speaker + dialogue line, and still_prompt of that character mid-speech (expressive face/mouth)
- If real-world / lifestyle / nature / food / travel: mode "stock" with concrete Pexels queries that name the user's nouns
- Spoken lines: short, punchy, on-topic — like a viral reel VO, not a corporate script
- No hashtags, no emojis, no URLs in JSON fields
"""


_DIRECTOR_CHARACTER = """You are Mira Creative Director specializing in talking-character shorts.
The user wants characters that TALK (fruits, animals, objects, fantasy beings).
Plan a real conversation between them — not silent B-roll.

Return ONLY valid JSON:
{
  "title": "short title",
  "mood": "playful|dramatic|funny|warm",
  "style": "dialogue",
  "mode": "character",
  "beats": [
    {
      "heading": "SPEAKER NAME",
      "speaker": "Lemon",
      "line": "Hey Banana, listen — I have something to tell you.",
      "still_prompt": "anthropomorphic lemon character with eyes and mouth speaking, Pixar style, expressive, studio light, no text, no watermark"
    }
  ]
}

Rules:
- beats = N different dialogue turns (alternate speakers)
- still_prompt MUST show that speaker as a talking character (face/mouth), matching the user's subject
- lines are first-person dialogue between them
- Stay on the user's exact subject (if fruits — fruits; never office)
- No hashtags, no emojis, no URLs
"""


def _load_api_key(name: str) -> str:
    v = (os.getenv(name) or "").strip()
    if v:
        return v
    keys_path = ROOT / "config" / "api_keys.json"
    if keys_path.is_file():
        try:
            data = json.loads(keys_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get(name.replace("_API_KEY", "").lower()):
                # map GROQ_API_KEY → groq etc.
                pass
            key_map = {
                "GROQ_API_KEY": "groq",
                "OPENROUTER_API_KEY": "openrouter",
                "NVIDIA_API_KEY": "nvidia",
                "ANTHROPIC_API_KEY": "anthropic",
                "GEMINI_API_KEY": "gemini",
            }
            short = key_map.get(name, "")
            if short and data.get(short):
                return str(data[short]).strip()
        except Exception:
            pass
    return ""


def _llm_json(system: str, user: str, *, timeout: float = 12.0) -> dict[str, Any] | None:
    """Fast LLM call via Groq/OpenRouter/NVIDIA — returns parsed JSON or None."""
    providers = [
        (
            "groq",
            "https://api.groq.com/openai/v1",
            _load_api_key("GROQ_API_KEY"),
            os.getenv("GROQ_MODEL") or "llama-3.3-70b-versatile",
        ),
        (
            "groq",
            "https://api.groq.com/openai/v1",
            _load_api_key("GROQ_API_KEY"),
            "llama-3.3-70b-versatile",
        ),
        (
            "groq",
            "https://api.groq.com/openai/v1",
            _load_api_key("GROQ_API_KEY"),
            "llama-3.1-8b-instant",
        ),
        (
            "openrouter",
            "https://openrouter.ai/api/v1",
            _load_api_key("OPENROUTER_API_KEY"),
            os.getenv("OPENROUTER_MODEL") or "openrouter/free",
        ),
        (
            "nvidia",
            "https://integrate.api.nvidia.com/v1",
            _load_api_key("NVIDIA_API_KEY"),
            os.getenv("NVIDIA_MODEL") or "meta/llama-3.1-8b-instruct",
        ),
    ]
    seen: set[str] = set()
    uniq = []
    for row in providers:
        key = f"{row[0]}:{row[3]}"
        if key in seen or not row[2]:
            continue
        seen.add(key)
        uniq.append(row)

    for name, base, key, model in uniq:
        try:
            text = _chat_completion(
                base_url=base,
                api_key=key,
                model=model,
                system=system,
                user=user,
                timeout=timeout,
                extra_headers=(
                    {
                        "HTTP-Referer": "https://github.com/jarvis-local",
                        "X-Title": "Mira Director",
                    }
                    if name == "openrouter"
                    else None
                ),
            )
            data = _extract_json(text or "")
            if data and isinstance(data.get("beats"), list) and data["beats"]:
                data["_director"] = f"{name}:{model}"
                return data
        except Exception as exc:
            logger.info("Mira director %s/%s failed: %s", name, model, exc)
            continue
    return None


def _chat_completion(
    *,
    base_url: str,
    api_key: str,
    model: str,
    system: str,
    user: str,
    timeout: float,
    extra_headers: dict[str, str] | None = None,
) -> str:
    """OpenAI-compatible chat — openai SDK if present, else urllib."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.55,
        "max_tokens": 900,
    }
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            default_headers=extra_headers,
        )
        resp = client.chat.completions.create(**payload)
        return (resp.choices[0].message.content or "").strip()
    except ImportError:
        pass

    import urllib.error
    import urllib.request

    url = base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        err = exc.read().decode("utf-8", errors="ignore")[:300]
        raise RuntimeError(f"HTTP {exc.code}: {err}") from exc
    choices = body.get("choices") or []
    if not choices:
        raise RuntimeError(f"no choices: {str(body)[:200]}")
    msg = choices[0].get("message") or {}
    return str(msg.get("content") or "").strip()


def _extract_json(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    # strip fences
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", raw)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None


def _clean_query(q: str, fallback: str) -> str:
    q = re.sub(r"\s+", " ", (q or "").strip())
    q = re.sub(r"[^\w\s\-]", " ", q)
    q = re.sub(r"\s+", " ", q).strip()
    if len(q.split()) < 2:
        return fallback
    return q[:90]


def _clean_line(line: str, fallback: str) -> str:
    line = re.sub(r"\s+", " ", (line or "").strip())
    line = line.strip("\"'")
    if len(line) < 8:
        return fallback
    # Keep spoken VO short
    words = line.split()
    if len(words) > 18:
        line = " ".join(words[:18])
    return line


def _heuristic_plan(topic: str, n: int, *, character: bool = False, mood: str | None = None) -> dict[str, Any]:
    """Strong offline planner — works for any topic without an LLM."""
    from jarvis.mira.formats import MOODS

    t = re.sub(r"\s+", " ", (topic or "cinematic scene").strip())
    t = re.sub(
        r"\b(make|create|generate|produce|shoot|render|video|clip|reel|about|of|for|please|a|an|the)\b",
        " ",
        t,
        flags=re.I,
    )
    t = re.sub(r"\s+", " ", t).strip() or "cinematic scene"
    core = t[:70]
    lower = f" {core.lower()} "
    mood_key = (mood or "").strip().lower() or None

    def _has(*words: str) -> bool:
        return any(re.search(rf"\b{re.escape(w)}\b", lower) for w in words)

    # Talking fruits / veggies only when the topic is actually about fruit
    if (_has("talking", "talk", "speak") or character) and _has(
        "fruit", "fruits", "vegetable", "lemon", "banana", "apple", "orange", "watermelon", "grape"
    ):
        cast = ["Lemon", "Banana", "Apple", "Watermelon", "Orange", "Grape"]
        if _has("banana"):
            cast = ["Banana", "Apple", "Lemon", "Orange"]
        lines = [
            "Hey — can we talk for a second?",
            "I've been thinking about us all day.",
            "You always steal the spotlight, you know.",
            "Maybe we're sweeter when we stick together.",
            "Alright… I'll listen. What do you need?",
            "Then it's settled. Friends till the last bite.",
        ]
        beats = []
        for i in range(n):
            sp = cast[i % len(cast)]
            beats.append(
                {
                    "heading": sp.upper(),
                    "speaker": sp,
                    "line": lines[i % len(lines)],
                    "query": f"{sp.lower()} fruit close up cinematic",
                    "still_prompt": (
                        f"anthropomorphic {sp.lower()} fruit character with big eyes and a mouth mid-speech, "
                        f"expressive talking face, Pixar style, soft studio lighting, no text, no watermark"
                    ),
                }
            )
        return {
            "title": "Fruits Talking",
            "mood": "playful",
            "style": "dialogue",
            "mode": "character",
            "beats": beats,
            "_director": "heuristic_character",
        }

    if character:
        # Generic talking subject from topic nouns — never invent fruits
        stop = {
            "talking", "talk", "speak", "speaking", "themselves", "itself", "about",
            "with", "from", "make", "video", "clip", "their", "them", "arguing",
            "argue", "conversation", "dialogue", "dialog", "chat", "chatting",
        }
        nouns = [
            w for w in re.findall(r"[a-zA-Z]+", core)
            if len(w) > 2 and w.lower() not in stop
        ][:4] or ["Hero", "Friend"]
        # Prefer concrete subjects (cats) over verbs leftover
        while len(nouns) < 2:
            nouns.append("Friend")
        # Deduplicate while preserving order
        seen_n: list[str] = []
        for n0 in nouns:
            if n0.lower() not in {x.lower() for x in seen_n}:
                seen_n.append(n0)
        nouns = seen_n
        if len(nouns) == 1:
            nouns.append("Friend")
        beats = []
        for i in range(n):
            sp = nouns[i % len(nouns)].title()
            other = nouns[(i + 1) % len(nouns)].title()
            q_base = nouns[0].lower()
            beats.append(
                {
                    "heading": sp.upper(),
                    "speaker": sp,
                    "line": f"Listen {other} — this matters to me.",
                    "query": f"{q_base} close up cinematic" if i % 2 == 0 else f"{sp.lower()} portrait cinematic",
                    "still_prompt": (
                        f"anthropomorphic {sp.lower()} character talking with expressive mouth, "
                        f"cinematic portrait, detailed, no text, no watermark"
                    ),
                }
            )
        return {
            "title": core[:48],
            "mood": "playful",
            "style": "dialogue",
            "mode": "character",
            "beats": beats,
            "_director": "heuristic_character",
        }

    domain_extra: list[str] = []
    if _has("fruit", "fruits", "vegetable", "apple", "banana", "orange"):
        domain_extra = ["fresh fruit close up", "colorful fruits market", "fruit still life cinematic"]
    elif _has("scuba", "underwater", "coral", "reef", "dive", "diving"):
        domain_extra = ["scuba diver underwater", "coral reef fish", "underwater ocean blue"]
    elif _has("guitar", "music", "concert", "piano", "dj", "band", "singer", "rooftop"):
        domain_extra = ["musician playing guitar", "rooftop sunset city", "live music performance"]
    elif _has("bangkok", "tokyo", "street", "vendor", "market", "travel", "vacation", "tour", "city", "beach", "mountain"):
        domain_extra = ["street food night market", "neon city street night", "travel destination aerial"]
    elif _has("cook", "food", "recipe", "kitchen", "restaurant", "baking", "bake", "cookies", "chef"):
        domain_extra = ["chef cooking kitchen", "food plating close up", "baking cookies oven"]
    elif _has("car", "drive", "driving", "racing", "motorcycle", "road"):
        domain_extra = ["car driving highway cinematic", "dashboard road view", "sports car exterior"]
    elif _has("gym", "fitness", "workout", "sport", "football", "soccer", "basketball"):
        domain_extra = ["athlete training gym", "sports action motion", "fitness workout"]
    elif _has(
        "api", "sdk", "docs", "dashboard", "console", "saas", "software",
        "website", "login", "endpoint", "developer", "platform",
    ):
        # Product/API asks → UI/docs only (never fashion portraits)
        domain_extra = [
            f"{core} website interface screen",
            f"{core} documentation page",
            f"{core} product dashboard UI",
        ]
    elif _has("tech", "code", "coding", "ai", "startup", "office", "laptop"):
        domain_extra = [
            "laptop screen code editor",
            "modern desk computer monitor UI",
            "developer workstation screen close up",
        ]
    elif _has("love", "wedding", "romance", "couple"):
        domain_extra = ["couple walking romantic", "wedding celebration", "holding hands close up"]
    elif _has("nature", "forest", "ocean", "sunset", "rain", "storm", "landscape"):
        domain_extra = ["nature landscape cinematic", "dramatic sky weather", "forest sunlight"]
    elif _has("fashion", "style", "model", "runway"):
        domain_extra = ["fashion model walking", "clothing detail close up", "stylish urban portrait"]
    elif _has("product", "unbox", "unboxing", "review", "commercial"):
        domain_extra = ["product showcase table", "hands holding product", "lifestyle product use"]
    elif _has("google", "youtube", "facebook", "instagram", "tiktok", "chrome", "android"):
        domain_extra = ["logo screen close up", "search bar typing", "smartphone app interface"]
    elif _has("night"):
        domain_extra = ["city night lights cinematic", "neon street night", "night atmosphere urban"]

    # Keep every angle ON the subject — "people lifestyle" pulled random portraits off-brief
    angles = [
        f"{core}",
        f"{core} cinematic wide",
        f"{core} close up detail",
        f"{core} atmosphere mood",
        f"{core} motion action",
        f"{core} sharp photoreal",
    ]
    # Append domain hints — never replace the user's core query
    for extra in domain_extra:
        if core.lower() not in extra.lower():
            angles.append(f"{core} {extra}")
        else:
            angles.append(extra)

    headings = ["OPEN", "LOOK", "DETAIL", "FEEL", "MOVE", "CLOSE"]
    # Exact-ask VO only — never invent "what X is" explainers / coach spam
    line_bank = [core] * 6
    if mood_key == "funny":
        line_bank = [f"{core}.", f"{core} — funny take.", core, core, core, core]
    elif mood_key == "sad":
        line_bank = [core, f"{core}.", core, core, core, core]
    elif mood_key == "angry":
        line_bank = [core, f"{core}.", core, core, core, core]
    elif mood_key == "epic":
        line_bank = [core, f"{core}.", core, core, core, core]
    elif mood_key and mood_key in MOODS:
        line_bank = [core, f"{core}.", core, core, core, core]

    beats = []
    for i in range(n):
        beats.append(
            {
                "heading": headings[i % len(headings)],
                "line": line_bank[i % len(line_bank)],
                "query": angles[i % len(angles)][:90],
                "speaker": "",
                "still_prompt": "",
            }
        )
    return {
        "title": core[:48],
        "mood": mood_key or "cinematic",
        "style": "cinematic",
        "mode": "stock",
        "beats": beats,
        "_director": "heuristic",
    }


def plan_video(
    topic: str,
    *,
    n_beats: int = 4,
    duration_sec: int = 30,
    audio_mode: str = "voice",
    user_script: str | None = None,
    force_character: bool = False,
    mood: str | None = None,
) -> dict[str, Any]:
    """Plan any user topic into N beats with queries + VO lines."""
    from jarvis.mira.brief_match import needs_fantasy_characters, plan_match_score
    from jarvis.mira.formats import MOODS

    n = max(3, min(6, int(n_beats or 4)))
    topic = re.sub(r"\s+", " ", (topic or "").strip()) or "cinematic scene"
    character = bool(force_character or needs_fantasy_characters(topic))
    mood_key = (mood or "").strip().lower() or None
    mood_hint = ""
    if mood_key and mood_key in MOODS:
        mood_hint = MOODS[mood_key]["vo_hint"]

    user = (
        f"Topic / exact brief: {topic}\n"
        f"Beats needed: {n}\n"
        f"Target length: ~{duration_sec}s\n"
        f"Audio mode: {audio_mode}\n"
        f"Character/dialogue mode: {'YES — talking characters required' if character else 'auto'}\n"
    )
    if mood_key:
        user += f"MOOD / emotional tone (REQUIRED): {mood_key} — {mood_hint}\n"
        user += "Every spoken line must match this mood. Do not ignore it.\n"
    if user_script and user_script.strip():
        user += f"User script / notes (honor this):\n{user_script.strip()[:600]}\n"

    system = _DIRECTOR_CHARACTER if character else _DIRECTOR_SYSTEM
    planned = _llm_json(system, user)
    if not planned:
        planned = _heuristic_plan(topic, n, character=character, mood=mood_key)
    else:
        beats_in = [b for b in planned.get("beats") or [] if isinstance(b, dict)]
        fallback = _heuristic_plan(topic, n, character=character, mood=mood_key)
        beats: list[dict[str, str]] = []
        for i in range(n):
            src = beats_in[i] if i < len(beats_in) else fallback["beats"][i]
            fb = fallback["beats"][i]
            beat = {
                "heading": (str(src.get("heading") or fb["heading"]).strip().upper()[:28] or fb["heading"]),
                "line": _clean_line(str(src.get("line") or ""), fb["line"]),
                "query": _clean_query(str(src.get("query") or ""), fb.get("query") or topic),
                "speaker": str(src.get("speaker") or fb.get("speaker") or "").strip()[:32],
                "still_prompt": str(src.get("still_prompt") or fb.get("still_prompt") or "").strip()[:480],
            }
            beats.append(beat)
        planned["beats"] = beats
        planned.setdefault("title", topic[:48])
        planned.setdefault("mood", mood_key or "cinematic")
        planned.setdefault("style", "dialogue" if character else "cinematic")
        planned["mode"] = "character" if character else str(planned.get("mode") or "stock")
    if mood_key:
        planned["mood"] = mood_key

    # Compliance: if plan mismatches, retry in character mode ONLY when brief needs it
    match = plan_match_score(topic, planned)
    planned["_match"] = match
    if not match.get("ok") and not character and needs_fantasy_characters(topic):
        retry = _llm_json(_DIRECTOR_CHARACTER, user + "\nIMPORTANT: previous plan mismatched. Match the brief exactly.\n")
        if retry and isinstance(retry.get("beats"), list):
            planned = retry
            planned["mode"] = "character"
            planned["_director"] = (planned.get("_director") or "retry") + "+match"
            fb = _heuristic_plan(topic, n, character=True, mood=mood_key)
            beats = []
            raw_beats = [b for b in planned.get("beats") or [] if isinstance(b, dict)]
            for i in range(n):
                src = raw_beats[i] if i < len(raw_beats) else fb["beats"][i]
                fb_b = fb["beats"][i]
                beats.append(
                    {
                        "heading": str(src.get("heading") or fb_b["heading"])[:28],
                        "line": _clean_line(str(src.get("line") or ""), fb_b["line"]),
                        "query": _clean_query(str(src.get("query") or ""), fb_b.get("query") or topic),
                        "speaker": str(src.get("speaker") or fb_b.get("speaker") or "")[:32],
                        "still_prompt": str(src.get("still_prompt") or fb_b.get("still_prompt") or "")[:480],
                    }
                )
            planned["beats"] = beats
            planned["_match"] = plan_match_score(topic, planned)
        else:
            planned = _heuristic_plan(topic, n, character=True, mood=mood_key)
            planned["_match"] = plan_match_score(topic, planned)
    elif not match.get("ok") and not character:
        # Stock rematch — keep stock mode; never invent talking fruit for travel/cafe asks
        rematch = _heuristic_plan(topic, n, character=False, mood=mood_key)
        rematch["_match"] = plan_match_score(topic, rematch)
        if float(rematch["_match"].get("score") or 0) >= float(match.get("score") or 0):
            planned = rematch
            planned["_director"] = "heuristic+rematch"
        else:
            planned["_match"] = match
    elif not match.get("ok") and character:
        # Force strong heuristic dialogue plan matching the actual subjects
        planned = _heuristic_plan(topic, n, character=True, mood=mood_key)
        planned["_match"] = plan_match_score(topic, planned)

    if user_script and user_script.strip():
        parts = re.split(r"(?<=[.!?])\s+|\n+", user_script.strip())
        parts = [p.strip() for p in parts if p.strip()]
        if len(parts) >= 2:
            for i, beat in enumerate(planned["beats"]):
                if i < len(parts):
                    beat["line"] = _clean_line(parts[i], beat["line"])

    return planned
