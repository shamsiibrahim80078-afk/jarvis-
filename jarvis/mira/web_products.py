"""Resolve ANY web product / SaaS / API ask into a live Mira tour — not a fixed list.

Known platforms in platforms.py stay first. When the Owner asks for something else
(e.g. "Eleven Labs API key", "Stripe docs", "Notion"), we map it to a real site and
screen-record — never invent random AI portraits / stock for product asks.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def _norm(text: str) -> str:
    t = (text or "").lower()
    t = re.sub(r"[^\w\s.\-/]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


# Common products Mira should open live (extend freely — not a hard ceiling)
_PRODUCT_HOMES: dict[str, dict[str, Any]] = {
    "elevenlabs": {
        "name": "ElevenLabs",
        "aliases": (
            "eleven labs",
            "elevenlabs",
            "11 labs",
            "11labs",
            "eleven lab",
        ),
        "home": "https://elevenlabs.io",
        "steps": (
            {
                "url": "https://elevenlabs.io",
                "dwell_sec": 7.0,
                "scrolls": (0, 700, 1400, 2200),
                "line": "ElevenLabs home — AI voice and speech products for creators and developers.",
            },
            {
                "url": "https://elevenlabs.io/docs/api-reference/authentication",
                "dwell_sec": 8.0,
                "scrolls": (0, 600, 1200, 2000),
                "line": "API authentication docs show how to create and use your ElevenLabs API key securely.",
            },
            {
                "url": "https://elevenlabs.io/docs/quickstart",
                "dwell_sec": 7.0,
                "scrolls": (0, 700, 1400),
                "line": "Quickstart walks through getting started with the ElevenLabs API and first requests.",
            },
            {
                "url": "https://elevenlabs.io/app",
                "dwell_sec": 7.5,
                "scrolls": (0, 400, 900),
                "line": "The ElevenLabs app is where you open the product UI, voices, and account settings including API keys.",
            },
            {
                "url": "https://elevenlabs.io/docs/api-reference/text-to-speech",
                "dwell_sec": 6.5,
                "scrolls": (0, 800, 1600),
                "line": "Text-to-speech API reference — the endpoints you call with your API key.",
            },
        ),
    },
    "fishaudio": {
        "name": "Fish Audio",
        "aliases": ("fish audio", "fish.audio", "fishaudio"),
        "home": "https://fish.audio",
        "steps": (
            {
                "url": "https://fish.audio",
                "dwell_sec": 6.5,
                "scrolls": (0, 700, 1400),
                "line": "Fish Audio — AI voice platform for speech and cloning.",
            },
            {
                "url": "https://fish.audio/docs",
                "dwell_sec": 7.0,
                "scrolls": (0, 800, 1600),
                "line": "Fish Audio docs cover APIs and how developers authenticate with keys.",
            },
        ),
    },
    "groq": {
        "name": "Groq",
        "aliases": ("groq", "groq cloud", "groq api"),
        "home": "https://console.groq.com",
        "steps": (
            {
                "url": "https://groq.com",
                "dwell_sec": 6.0,
                "scrolls": (0, 700, 1400),
                "line": "Groq — fast AI inference for developers.",
            },
            {
                "url": "https://console.groq.com/keys",
                "dwell_sec": 7.0,
                "scrolls": (0, 400, 800),
                "line": "Groq console API keys — where you create and manage keys for the API.",
            },
            {
                "url": "https://console.groq.com/docs/quickstart",
                "dwell_sec": 6.5,
                "scrolls": (0, 700, 1400),
                "line": "Groq quickstart docs show how to call models with your API key.",
            },
        ),
    },
    "stripe": {
        "name": "Stripe",
        "aliases": ("stripe", "stripe api", "stripe.com"),
        "home": "https://stripe.com",
        "steps": (
            {
                "url": "https://stripe.com",
                "dwell_sec": 6.0,
                "scrolls": (0, 800, 1600),
                "line": "Stripe home — payments infrastructure for the internet.",
            },
            {
                "url": "https://docs.stripe.com/keys",
                "dwell_sec": 7.0,
                "scrolls": (0, 700, 1400),
                "line": "Stripe API keys docs — publishable and secret keys for your integration.",
            },
            {
                "url": "https://docs.stripe.com",
                "dwell_sec": 6.5,
                "scrolls": (0, 800, 1600),
                "line": "Stripe documentation hub for APIs, SDKs, and guides.",
            },
        ),
    },
    "notion": {
        "name": "Notion",
        "aliases": ("notion", "notion.so", "notion api"),
        "home": "https://www.notion.so",
        "steps": (
            {
                "url": "https://www.notion.so/product",
                "dwell_sec": 6.5,
                "scrolls": (0, 800, 1600),
                "line": "Notion product — docs, wikis, and projects in one workspace.",
            },
            {
                "url": "https://developers.notion.com",
                "dwell_sec": 7.0,
                "scrolls": (0, 700, 1400),
                "line": "Notion developers — API docs and how to create an integration token.",
            },
        ),
    },
    "openai": {
        "name": "OpenAI",
        "aliases": ("openai", "openai api", "openai platform"),
        "home": "https://platform.openai.com",
        "steps": (
            {
                "url": "https://platform.openai.com",
                "dwell_sec": 6.0,
                "scrolls": (0, 500, 1000),
                "line": "OpenAI platform — where developers build with GPT models.",
            },
            {
                "url": "https://platform.openai.com/api-keys",
                "dwell_sec": 7.0,
                "scrolls": (0, 400, 800),
                "line": "API keys page — create and manage OpenAI secret keys.",
            },
            {
                "url": "https://platform.openai.com/docs",
                "dwell_sec": 6.5,
                "scrolls": (0, 800, 1600),
                "line": "OpenAI docs — guides and API reference for developers.",
            },
        ),
    },
}

_LIFESTYLE_RE = re.compile(
    r"\b(dog|dogs|cat|cats|puppy|sunset|sunrise|beach|ocean|mountain|forest|"
    r"coffee|cooking|recipe|travel|wedding|flower|flowers|car\s+drive|"
    r"motivational\s+quote|nature\s+walk|yoga|gym\s+workout)\b",
    re.I,
)

_PRODUCT_SIGNAL_RE = re.compile(
    r"\b("
    r"api\s*keys?|sdk|docs?|documentation|dashboard|console|developer|"
    r"saas|web\s*app|login|sign[\s-]?up|pricing|"
    r"integration|webhook|endpoint|oauth|token|secret\s*key|"
    r"how\s+to\s+(get|create|make|find)\s+(an?\s+)?(api|key|token)|"
    r"screen\s*record|walk\s*through|"
    r"(site|app|product|platform)\s+tour|"
    r"tour\s+(the\s+)?(site|app|product|platform)|"
    r"explore\s+the\s+(site|app|product)"
    r")\b",
    re.I,
)


def looks_like_web_product_ask(text: str) -> bool:
    """True when the ask is about a real product/site/API — not lifestyle B-roll."""
    t = _norm(text)
    if not t:
        return False
    if _LIFESTYLE_RE.search(t) and not _PRODUCT_SIGNAL_RE.search(t):
        # "dog api" rare — if only lifestyle nouns, stock is OK
        if not any(a in t for meta in _PRODUCT_HOMES.values() for a in meta.get("aliases") or ()):
            return False
    if _PRODUCT_SIGNAL_RE.search(t):
        return True
    # Named product from catalog
    for meta in _PRODUCT_HOMES.values():
        for a in meta.get("aliases") or ():
            if _norm(str(a)) and _norm(str(a)) in t:
                return True
    # Explicit URL
    if re.search(r"https?://|www\.\w+", t):
        return True
    # Brand-ish name + software cue (avoid bare labs/app lifestyle false positives)
    if re.search(
        r"\b([a-z0-9]{3,})(?:\s+[a-z0-9]{2,}){0,2}\s+"
        r"(app|ai|labs|soft(?:ware)?|cloud|studio|hub)\b",
        t,
    ) or re.search(
        r"\b(app|ai|labs|soft(?:ware)?|cloud|studio|hub)\s+"
        r"([a-z0-9]{3,}(?:\s+[a-z0-9]{2,}){0,2})\b",
        t,
    ):
        if _LIFESTYLE_RE.search(t) and not _PRODUCT_SIGNAL_RE.search(t):
            return False
        return True
    return False


def _match_catalog(text: str) -> tuple[str, dict[str, Any]] | None:
    t = _norm(text)
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for key, meta in _PRODUCT_HOMES.items():
        for alias in meta.get("aliases") or ():
            a = _norm(str(alias))
            if not a or len(a) < 3:
                continue
            if re.search(rf"(?:^|[\s\-_/]){re.escape(a)}(?:$|[\s\-_/.,!?])", t) or a == t:
                ranked.append((len(a), key, meta))
                break
            if len(a) >= 5 and a in t:
                ranked.append((len(a), key, meta))
                break
    if not ranked:
        return None
    ranked.sort(key=lambda x: -x[0])
    return ranked[0][1], ranked[0][2]


def _prefer_api_key_steps(steps: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    """When ask mentions API key, put auth/keys/docs pages first."""
    if not re.search(r"\b(api\s*keys?|secret\s*key|access\s*token|auth)\b", text, re.I):
        return steps
    scored: list[tuple[int, dict[str, Any]]] = []
    for s in steps:
        blob = f"{s.get('url', '')} {s.get('line', '')}".lower()
        score = 0
        if "api" in blob:
            score += 3
        if "key" in blob or "auth" in blob:
            score += 5
        if "docs" in blob or "reference" in blob:
            score += 2
        if "quickstart" in blob:
            score += 2
        scored.append((score, s))
    scored.sort(key=lambda x: -x[0])
    # Keep high-score first but include the rest
    return [s for _sc, s in scored]


def _guess_home_from_brand(text: str) -> tuple[str, str] | None:
    """Best-effort brand → https://brand.com|.io|.ai for unknown products."""
    t = _norm(text)
    # Never invent sites for school / lifestyle / travel phrasing
    if re.search(
        r"\b(classroom|school|university|college|homework|teacher|student|"
        r"dog|dogs|cat|cats|sunset|sunrise|beach|ocean|mountain|forest|"
        r"travel|vacation|wedding|cooking|recipe|yoga|gym|science\s+lab)\b",
        t,
    ):
        return None
    t = re.sub(
        r"\b(create|make|generate|full|video|clip|tour|of|about|for|the|an?|my|"
        r"api|keys?|docs?|documentation|how\s+to|get|screen\s*record)\b",
        " ",
        t,
    )
    t = re.sub(r"\s+", " ", t).strip()
    if not t or len(t) < 3:
        return None
    # Prefer multi-word brands joined
    slug = re.sub(r"[^a-z0-9]+", "", t)
    if len(slug) < 3 or len(slug) > 32:
        return None
    name = t.title()
    # Prefer .io for AI tools, else .com
    if any(x in t for x in ("ai", "lab", "labs", "llm", "voice", "speech")):
        home = f"https://{slug}.io"
    else:
        home = f"https://{slug}.com"
    return name, home


def _dynamic_steps(name: str, home: str, text: str) -> list[dict[str, Any]]:
    base = home.rstrip("/")
    steps: list[dict[str, Any]] = [
        {
            "url": base + "/",
            "dwell_sec": 7.0,
            "scrolls": (0, 700, 1400, 2200),
            "line": f"{name} homepage — opening the live product site for this tour.",
        },
        {
            "url": f"{base}/docs",
            "dwell_sec": 7.0,
            "scrolls": (0, 800, 1600),
            "line": f"{name} docs — documentation for developers and API usage.",
            "fallback_urls": (f"{base}/documentation", f"{base}/developers", f"{base}/api"),
        },
        {
            "url": f"{base}/pricing",
            "dwell_sec": 6.0,
            "scrolls": (0, 700, 1400),
            "line": f"{name} pricing — plans and how the product is offered.",
        },
    ]
    if re.search(r"\b(api\s*keys?|token|auth)\b", text, re.I):
        steps.insert(
            1,
            {
                "url": f"{base}/docs/api",
                "dwell_sec": 8.0,
                "scrolls": (0, 600, 1200, 2000),
                "line": f"{name} API docs — where API keys and authentication are explained.",
                "fallback_urls": (
                    f"{base}/api-keys",
                    f"{base}/account/api-keys",
                    f"{base}/settings/api-keys",
                    f"{base}/developers",
                ),
            },
        )
    return _prefer_api_key_steps(steps, text)


def resolve_web_product(text: str) -> dict[str, Any] | None:
    """Return a platform-shaped dict for live tour, or None (use stock for lifestyle)."""
    raw = (text or "").strip()
    if not raw:
        return None
    if not looks_like_web_product_ask(raw):
        return None

    # Explicit URL in ask
    m = re.search(r"https?://[^\s<>\"']+", raw, re.I)
    if m:
        url = m.group(0).rstrip(".,);]")
        host = urlparse(url).hostname or "site"
        name = host.replace("www.", "").split(".")[0].title()
        steps = _dynamic_steps(name, f"{urlparse(url).scheme}://{urlparse(url).netloc}", raw)
        steps[0] = {
            **steps[0],
            "url": url,
            "line": f"Opening the exact URL you named — {url}",
        }
        return {
            "id": re.sub(r"[^a-z0-9]+", "", name.lower())[:24] or "web",
            "name": name,
            "home": f"{urlparse(url).scheme}://{urlparse(url).netloc}",
            "steps": steps,
            "aliases": [],
            "_dynamic": True,
        }

    hit = _match_catalog(raw)
    if hit:
        key, meta = hit
        steps = [dict(s) for s in (meta.get("steps") or [])]
        steps = _prefer_api_key_steps(steps, raw)
        return {
            "id": key,
            "name": str(meta.get("name") or key),
            "home": str(meta.get("home") or ""),
            "steps": steps,
            "aliases": list(meta.get("aliases") or []),
            "_dynamic": True,
        }

    # Only invent a home URL when the ask clearly signals a product/API
    if not _PRODUCT_SIGNAL_RE.search(raw) and not re.search(
        r"\b(app|ai|labs|soft(?:ware)?|cloud|studio|hub)\b", raw, re.I
    ):
        return None
    guessed = _guess_home_from_brand(raw)
    if not guessed:
        return None
    name, home = guessed
    pid = re.sub(r"[^a-z0-9]+", "", name.lower())[:24] or "web"
    return {
        "id": pid,
        "name": name,
        "home": home,
        "steps": _dynamic_steps(name, home, raw),
        "aliases": [],
        "_dynamic": True,
        "_guessed": True,
    }
