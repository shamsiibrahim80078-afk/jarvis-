"""API key hunt intent — detect any 'get me X api' command without the brain."""

from __future__ import annotations

import re

from jarvis.context import get_context, set_context
from jarvis.tools.command_parse import normalize

# Phrases that mean "fetch an API key" — never send these to Groq
_HUNT_MARKERS = (
    "api key", "api keys", "get api", "fetch api", "grab api",
    "get key", "fetch key", "grab key", "my api key", "the api key",
    "sign in and get", "login and get", "get their api",
)

# Explicit .env save — never auto-write unless one of these matches
_ENV_SAVE_RE = re.compile(
    r"(?:"
    r"\b(?:save|put|post|write|add|dump|sync)\b.{0,40}\b(?:to|into|in)\b.{0,20}\.?env\b"
    r"|"
    r"\b(?:save|put|post|write|add)\b.{0,20}\.?env\b"
    r"|"
    r"\bpost\b.{0,40}\bapi\b.{0,20}\.?env\b"
    r")",
    re.I,
)

_CONTEXT_MARKERS = (
    "this ai", "that ai", "from there", "from here", "that one",
    "this one", "that site", "this site", "over there", "from that",
)

_GET_VERBS = re.compile(
    r"\b(get|fetch|grab|go\s+get|sign\s*in|log\s*in|login|retrieve|pull)\b",
    re.I,
)

_EXTRACT_PATTERNS = (
    r"(?:get|fetch|grab|go\s+get|login|sign\s*in)\s+(?:me\s+)?(?:the\s+)?(?:a\s+)?(.+?)\s+api\s*keys?",
    r"(?:get|fetch|grab|go\s+get)\s+(?:me\s+)?(?:the\s+)?(?:a\s+)?(.+?)\s+keys?",
    r"(?:get|fetch|grab)\s+(?:me\s+)?(?:the\s+)?api\s*keys?\s+(?:for|from|of)\s+(.+)",
    r"(?:get|fetch|grab)\s+(?:me\s+)?(?:the\s+)?(.+?)\s+api\b",
    r"(?:sign\s*in|log\s*in|login)\s+(?:to\s+)?(.+?)(?:\s+and\s+get|\s+for\s+api|$)",
)


def wants_env_save(text: str) -> bool:
    """True only when the user explicitly asks to write a key into .env."""
    lower = normalize(text)
    if not lower:
        return False
    # Normalize common speech: "dot env" / "dotenv" → env
    compact = (
        lower.replace("dot env", "env")
        .replace("dotenv", "env")
        .replace(". env", "env")
    )
    if _ENV_SAVE_RE.search(compact) or _ENV_SAVE_RE.search(lower):
        return True
    # Phrase list for exact-ish matches from the product brief
    phrases = (
        "save it to env", "save to env", "save to .env", "save into .env",
        "put it in .env", "put it in env", "put in .env",
        "post that api into .env", "post to .env", "post into .env",
        "write it to env", "write it to .env", "write to env", "write to .env",
        "add it to env", "add it to .env", "add to env", "add to .env",
    )
    return any(p in lower or p in compact for p in phrases)


def is_api_hunt_intent(text: str) -> bool:
    """True if command should route to API hunter, never the LLM brain."""
    lower = normalize(text)
    if not lower:
        return False

    # Saving / remembering a sheet link is NOT a hunt
    if "remember" in lower:
        return False
    if is_api_count_command_safe(lower):
        return False

    # Scoped sheet batch — not a single-provider hunt
    try:
        from jarvis.tools.api_pipeline import is_batch_api_command
        if is_batch_api_command(text):
            return False
    except Exception:
        pass
    if "phantom" in lower and re.search(r"\bapis?\b", lower):
        return False
    if re.search(r"from\s+(?:row\s+)?\d+", lower) and re.search(r"\bapis?\b", lower):
        return False
    if ("paste" in lower or "put" in lower) and "sheet" in lower and re.search(r"\bapis?\b", lower):
        return False
    if "apis from sheet" in lower or "all apis from" in lower or "get all api" in lower:
        return False

    # Explicit .env save for a provider/api — Phase 1 only
    if wants_env_save(text) and re.search(r"\b(api|key|keys|env)\b", lower):
        return True
    if wants_env_save(text):
        from jarvis.tools.api_hunter import detect_provider
        if detect_provider(text):
            return True

    if any(m in lower for m in _HUNT_MARKERS):
        return True

    if _GET_VERBS.search(lower) and re.search(r"\b(api|key|keys)\b", lower):
        return True

    if any(m in lower for m in _CONTEXT_MARKERS) and _GET_VERBS.search(lower):
        return True

    # Direct URL with api/key words
    from jarvis.tools.command_parse import extract_urls
    urls = extract_urls(text)
    if urls and re.search(r"\b(api|key|keys)\b", lower):
        # Spreadsheet links with "api sheet" wording are saves/opens, not hunts
        if "sheet" in lower or "docs.google.com/spreadsheets" in lower:
            return False
        return True

    # "get me groq" / "get me eleven labs" — provider name + get verb
    from jarvis.tools.api_hunter import detect_provider

    if _GET_VERBS.search(lower) and detect_provider(text):
        return True

    return False


def is_api_count_command_safe(lower: str) -> bool:
    """Lightweight count-intent check without importing api_pipeline (avoid cycles)."""
    if not re.search(r"\bapis?\b", lower):
        return False
    return bool(
        re.search(r"how\s+many", lower)
        or re.search(r"\b(left|remaining|missing|still|count|which|status|check)\b", lower)
    )


def extract_provider_query(text: str) -> str | None:
    """Pull a provider name out of messy speech."""
    lower = normalize(text)
    for pat in _EXTRACT_PATTERNS:
        m = re.search(pat, lower)
        if m:
            name = m.group(1).strip()
            name = re.sub(
                r"\b(the|my|a|an|for|from|their|its|this|that|please)\b",
                " ",
                name,
            )
            name = re.sub(r"\s+", " ", name).strip(" .,!?")
            if name and len(name) > 1 and name not in ("api", "key", "keys"):
                return name
    return None


def resolve_provider(text: str) -> str | None:
    """Best-effort provider id from speech + session context."""
    from jarvis.tools.api_hunter import detect_provider, fuzzy_match_provider, ensure_provider

    pid = detect_provider(text)
    if pid:
        set_context(None, last_provider=pid)
        return pid

    ctx = get_context()
    lower = normalize(text)

    if any(m in lower for m in _CONTEXT_MARKERS):
        if ctx.get("last_provider"):
            return str(ctx["last_provider"])
        if ctx.get("last_site"):
            pid = detect_provider(str(ctx["last_site"]))
            if pid:
                return pid

    raw = extract_provider_query(text)
    if raw:
        pid = fuzzy_match_provider(raw)
        if pid:
            set_context(None, last_provider=pid)
            return pid
        return ensure_provider(raw)

    # Bare "get the api key" / "save it to .env" — use last provider
    if is_api_hunt_intent(text):
        if ctx.get("last_provider"):
            return str(ctx["last_provider"])
        # Explicit env-save with no provider named — don't invent one
        if wants_env_save(text) and not _GET_VERBS.search(lower):
            return None
        # Prefer providers we already have credentials context for
        for fallback in ("elevenlabs", "groq", "fish"):
            set_context(None, last_provider=fallback)
            return fallback

    return None


def remember_site(url: str, label: str = "") -> None:
    """Track last opened site so 'get api from there' works."""
    from jarvis.tools.api_hunter import detect_provider

    pid = detect_provider(label or url)
    extra: dict[str, str] = {"last_site": url}
    if pid:
        extra["last_provider"] = pid
    set_context(None, **extra)
