"""Platform walkthroughs — open the real site, screen-record UI, narrate matching scenes.

When the user asks for Hugging Face / Cursor / ChatGPT / CryptoRafts / etc., Mira must
NOT invent random stock. It opens the platform, records the real UI after it paints,
trims the blank load flash, explores pages/features, and speaks only about what is shown.
"""

from __future__ import annotations

import logging
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)

# Public marketing / product pages that work without login for a deep tour.
_PLATFORMS: dict[str, dict[str, Any]] = {
    "huggingface": {
        "name": "Hugging Face",
        "aliases": (
            "hugging face",
            "huggingface",
            "hugging-face",
            "hf hub",
            "huggingface.co",
        ),
        "home": "https://huggingface.co",
        "steps": (
            {
                "url": "https://huggingface.co",
                "dwell_sec": 5.0,
                "scrolls": (500, 900, 1200),
                "line": "This is Hugging Face home — the hub for AI models, datasets, and community demos.",
            },
            {
                "url": "https://huggingface.co/models",
                "dwell_sec": 5.5,
                "scrolls": (600, 1100, 1600),
                "line": "Models lists open models you can search, filter by task, and open for details or download.",
            },
            {
                "url": "https://huggingface.co/datasets",
                "dwell_sec": 5.0,
                "scrolls": (600, 1100),
                "line": "Datasets is where training and evaluation data lives — browse, preview, and load into projects.",
            },
            {
                "url": "https://huggingface.co/spaces",
                "dwell_sec": 5.5,
                "scrolls": (600, 1100, 1500),
                "line": "Spaces hosts interactive demos so you can try models in the browser without local setup.",
            },
            {
                "url": "https://huggingface.co/docs",
                "dwell_sec": 4.5,
                "scrolls": (500, 900),
                "line": "Docs covers libraries, APIs, and guides for building on the Hugging Face stack.",
            },
        ),
    },
    "cursor": {
        "name": "Cursor",
        "aliases": ("cursor ai", "cursor.com", "cursor ide", "cursor editor", "cursor"),
        "home": "https://cursor.com",
        "steps": (
            {
                "url": "https://cursor.com",
                "dwell_sec": 5.5,
                "scrolls": (400, 900, 1400),
                "line": "Cursor's homepage introduces the AI-first code editor built for shipping software faster.",
            },
            {
                "url": "https://cursor.com/features",
                "dwell_sec": 5.5,
                "scrolls": (500, 1000, 1500),
                "line": "Features walks through chat, edits, agents, and codebase-aware tools inside the IDE.",
            },
            {
                "url": "https://cursor.com/pricing",
                "dwell_sec": 5.0,
                "scrolls": (400, 900),
                "line": "Pricing shows plans and what you get at each tier for individuals and teams.",
            },
            {
                "url": "https://cursor.com/changelog",
                "dwell_sec": 4.5,
                "scrolls": (500, 900),
                "line": "Changelog lists product updates so you can see new capabilities over time.",
            },
        ),
    },
    "chatgpt": {
        "name": "ChatGPT",
        "aliases": ("chat gpt", "chatgpt", "chat.openai", "openai chatgpt"),
        "home": "https://chatgpt.com",
        "steps": (
            {
                "url": "https://chatgpt.com",
                "dwell_sec": 6.0,
                "scrolls": (300, 600, 900),
                "line": "ChatGPT opens in the browser — this is the chat surface where you type prompts and get replies.",
            },
            {
                "url": "https://chatgpt.com",
                "dwell_sec": 5.0,
                "scrolls": (200, 500),
                "line": "From here you can start a new chat, sign in, or continue past conversations if you are logged in.",
            },
            {
                "url": "https://openai.com/chatgpt/overview/",
                "dwell_sec": 5.5,
                "scrolls": (500, 1000, 1400),
                "line": "OpenAI's ChatGPT overview explains the product, use cases, and how it fits everyday work.",
            },
            {
                "url": "https://openai.com/chatgpt/pricing/",
                "dwell_sec": 5.0,
                "scrolls": (400, 900),
                "line": "Pricing covers Free, Plus, and team options so you can see which plan matches your needs.",
            },
        ),
    },
    "cryptorafts": {
        "name": "CryptoRafts",
        "aliases": (
            "crypto rafts",
            "cryptorafts",
            "crypto-rafts",
            "crypto raft",
            "cryptoraft",
            "cryptorafts.com",
        ),
        "home": "https://cryptorafts.com",
        # One UNIQUE URL per scene — full scroll + explain every public page
        "steps": (
            {
                "url": "https://cryptorafts.com/",
                "dwell_sec": 9.0,
                "scrolls": (0, 1200, 2800, 4500, 6500),
                "line": (
                    "CryptoRafts home — BUILD, VERIFIED, PITCH, CONNECT. "
                    "A B2B Web3 network linking founders with VCs, exchanges, launchpads, agencies, and influencers on BNB Chain. "
                    "We scroll trust and KYC KYB, public dealflow, Atlas market intelligence, autonomous agents, AI risk scoring, "
                    "and the live Cryptorafts Network directory counts."
                ),
            },
            {
                "url": "https://cryptorafts.com/features",
                "dwell_sec": 12.0,
                "scrolls": (0, 1500, 3200, 5000, 7000, 9000),
                "line": (
                    "Features — the full product map. Role workspaces for founders, VCs, exchanges, IDO launchpads, influencers, and agencies. "
                    "KYC KYB, public dealflow, smart deal rooms, pitch management, analytics, investment pipelines, "
                    "exchange listings, IDO tools, influencer campaigns, agency services, spotlight, and team management. "
                    "AI workspace: copilot chat, BNB Chain agents, RaftsAI autonomous workforce, sixty-plus AI modules, "
                    "document intelligence, meeting AI, plans and credits, developer suite. "
                    "Security partners CertiK and Hashlock, ChainGPT, CryptoRank, MainHub on BSC, and on-chain credentials."
                ),
            },
            {
                "url": "https://cryptorafts.com/raftai-agent",
                "dwell_sec": 10.0,
                "scrolls": (0, 900, 2000, 3400, 4800),
                "line": (
                    "RaftAI Agent — the autonomous AI workforce. "
                    "It plans outcomes, runs specialist agents for research, marketing, fundraising, compliance, and ops, "
                    "asks for human approval before risky actions, monitors markets, and produces real business work products."
                ),
            },
            {
                "url": "https://cryptorafts.com/market-intelligence/control",
                "dwell_sec": 9.0,
                "scrolls": (0, 800, 1800, 3000, 4200),
                "line": (
                    "Atlas market intelligence — live prices, ConsensusScore, research terminal, and role dashboards. "
                    "Data foundation tracking millions of assets across hundreds of CEX and DEX venues."
                ),
            },
            {
                "url": "https://cryptorafts.com/dealflow",
                "dwell_sec": 8.0,
                "scrolls": (0, 700, 1600, 2800),
                "line": (
                    "Public dealflow — browse verified projects and opportunities with consistent profiles "
                    "so founders and investors see the same facts before a deal moves."
                ),
            },
            {
                "url": "https://cryptorafts.com/pricing",
                "dwell_sec": 7.5,
                "scrolls": (0, 600, 1400, 2400),
                "line": (
                    "Pricing — Starter, Pro, Business, and Enterprise with AI credits and seats "
                    "so teams can scale RaftAI and workspace tools."
                ),
            },
            {
                "url": "https://cryptorafts.com/airdrop",
                "dwell_sec": 7.0,
                "scrolls": (0, 700, 1500, 2400),
                "line": (
                    "Verified airdrop system — wallet campaigns with on-chain verification, "
                    "task tracking, and multi-reward support via MainHub on BSC."
                ),
            },
            {
                "url": "https://cryptorafts.com/login",
                "dwell_sec": 5.0,
                "scrolls": (0, 400),
                "line": "Login — founders, VCs, and partners sign in to open their role workspace.",
            },
            {
                "url": "https://cryptorafts.com/signup",
                "dwell_sec": 5.0,
                "scrolls": (0, 500),
                "line": "Sign up — create an account and pick your role on the Cryptorafts network.",
            },
            {
                "url": "https://cryptorafts.com/blog",
                "dwell_sec": 6.5,
                "scrolls": (0, 800, 1600, 2600),
                "line": "Blog — industry insights, platform updates, and education readable without login.",
            },
            {
                "url": "https://cryptorafts.com/whitepaper",
                "dwell_sec": 7.5,
                "scrolls": (0, 900, 1800, 2800),
                "line": (
                    "Whitepaper — verified identity, structured project data, "
                    "AI review, and portable on-chain credentials."
                ),
            },
            {
                "url": "https://cryptorafts.com/news",
                "dwell_sec": 6.5,
                "scrolls": (0, 700, 1500, 2400),
                "line": "News and learning hub — ChainGPT-powered headlines and guides for Web3 builders.",
            },
            {
                "url": "https://cryptorafts.com/contact",
                "dwell_sec": 5.0,
                "scrolls": (0, 500, 1000),
                "line": "Contact — reach Cryptorafts for partnerships and support.",
            },
        ),
    },

    "gemini": {
        "name": "Google Gemini",
        "aliases": (
            "google gemini",
            "gemini ai",
            "gemini.google",
            "gemini google",
            "bard gemini",
            "gemini app",
            "gemini",
        ),
        # Public marketing/docs only — gemini.google.com/app hangs/blank in headless
        "home": "https://ai.google.dev/",
        "steps": (
            {
                "url": "https://ai.google.dev/",
                "dwell_sec": 6.0,
                "scrolls": (0, 700, 1400),
                "line": "Google AI for developers is the hub for Gemini APIs, SDKs, and tools to ship AI features.",
                "fallback_urls": (
                    "https://blog.google/technology/ai/google-gemini-ai/",
                    "https://huggingface.co/",
                ),
            },
            {
                "url": "https://ai.google.dev/gemini-api/docs",
                "dwell_sec": 6.5,
                "scrolls": (0, 800, 1600, 2400),
                "line": "Gemini API docs show how developers build with Google's models — quickstarts, guides, and references.",
            },
            {
                "url": "https://deepmind.google/technologies/gemini/",
                "dwell_sec": 7.0,
                "scrolls": (0, 900, 1800, 2800),
                "line": "DeepMind's Gemini page — Google's multimodal AI model family for text, code, and images.",
            },
            {
                "url": "https://blog.google/technology/ai/google-gemini-ai/",
                "dwell_sec": 6.0,
                "scrolls": (0, 800, 1600),
                "line": "Google's Gemini announcement blog explains the product story and what the models can do.",
            },
        ),
    },

    "google": {
        "name": "Google",
        "aliases": ("google.com", "google search", "google"),
        "home": "https://www.google.com",
        "steps": (
            {
                "url": "https://www.google.com",
                "dwell_sec": 4.0,
                "scrolls": (100,),
                "line": "This is Google Search — type a query and get results from across the web.",
            },
            {
                "url": "https://www.google.com/search?q=artificial+intelligence",
                "dwell_sec": 5.0,
                "scrolls": (500, 1100, 1600),
                "line": "Search results show links, snippets, and related questions for your query.",
            },
            {
                "url": "https://www.google.com/search?q=artificial+intelligence&udm=2",
                "dwell_sec": 4.5,
                "scrolls": (400, 900),
                "line": "Image results let you browse visual matches for the same search.",
            },
        ),
    },
    "youtube": {
        "name": "YouTube",
        "aliases": ("youtube.com", "you tube", "youtube"),
        "home": "https://www.youtube.com",
        "steps": (
            {
                "url": "https://www.youtube.com",
                "dwell_sec": 5.0,
                "scrolls": (600, 1200, 1800),
                "line": "YouTube home shows the feed of videos, Shorts, and recommended channels.",
            },
            {
                "url": "https://www.youtube.com/feed/trending",
                "dwell_sec": 5.0,
                "scrolls": (600, 1200),
                "line": "Trending highlights popular uploads people are watching right now.",
            },
            {
                "url": "https://www.youtube.com/results?search_query=technology",
                "dwell_sec": 5.0,
                "scrolls": (500, 1100),
                "line": "Search results list videos matching your topic with titles and channels.",
            },
        ),
    },
    "github": {
        "name": "GitHub",
        "aliases": ("github.com", "git hub", "github"),
        "home": "https://github.com",
        "steps": (
            {
                "url": "https://github.com",
                "dwell_sec": 5.0,
                "scrolls": (400, 900, 1400),
                "line": "GitHub home is where developers host code, issues, and pull requests.",
            },
            {
                "url": "https://github.com/explore",
                "dwell_sec": 5.0,
                "scrolls": (500, 1100),
                "line": "Explore surfaces trending repositories and topics across the community.",
            },
            {
                "url": "https://github.com/topics/artificial-intelligence",
                "dwell_sec": 5.0,
                "scrolls": (500, 1100),
                "line": "Topic pages group related open-source projects you can star and fork.",
            },
        ),
    },
}


def _norm(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip().lower())
    t = re.sub(r"[^a-z0-9.\s\-]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def list_platforms() -> list[str]:
    return sorted(_PLATFORMS.keys())


def detect_platform(text: str) -> dict[str, Any] | None:
    """Return platform spec if the ask is mainly that product/site.

    Longer alias wins (e.g. 'google gemini' beats plain 'google').
    """
    t = _norm(text)
    if not t:
        return None
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for key, meta in _PLATFORMS.items():
        for alias in meta.get("aliases") or ():
            a = _norm(str(alias))
            if not a or len(a) < 3:
                continue
            # Prefer whole-word / clear phrase match — avoid tiny substring traps
            if re.search(rf"(?:^|[\s\-_/]){re.escape(a)}(?:$|[\s\-_/.,!?])", t) or a == t:
                ranked.append((len(a), key, meta))
                break
            if len(a) >= 5 and a in t:
                ranked.append((len(a), key, meta))
                break
    if not ranked:
        # Not in the built-in list — resolve ANY product/SaaS/API ask to a live tour
        # (ElevenLabs, Stripe, …). Lifestyle asks (dogs, sunsets) stay None → stock OK.
        try:
            from jarvis.mira.web_products import resolve_web_product

            dyn = resolve_web_product(text)
            if dyn:
                return dyn
        except Exception as exc:
            logger.debug("dynamic web product resolve skip: %s", exc)
        return None
    # Longer alias first; never let plain "google" beat "gemini" when both appear
    ranked.sort(key=lambda x: (-x[0], 0 if x[1] != "google" else 1))
    # If Gemini is named, force Gemini over Google Search
    if re.search(r"\bgemini\b", t):
        for _len, key, meta in ranked:
            if key == "gemini":
                return {
                    "id": key,
                    "name": str(meta.get("name") or key),
                    "home": str(meta.get("home") or ""),
                    "steps": list(meta.get("steps") or []),
                    "aliases": list(meta.get("aliases") or []),
                }
    _len, key, meta = ranked[0]
    return {
        "id": key,
        "name": str(meta.get("name") or key),
        "home": str(meta.get("home") or ""),
        "steps": list(meta.get("steps") or []),
        "aliases": list(meta.get("aliases") or []),
    }


def wants_platform_record(text: str) -> bool:
    """True when user wants a platform / product screen tour video.

    Any named known platform + create/video intent → always screen-record
    (never leave the door open for random stock).
    """
    if not detect_platform(text):
        return False
    t = _norm(text)
    # Known platform alone is enough when user is in Mira create path
    if re.search(
        r"\b(screen\s*record|record\s+(the\s+)?screen|walk\s*through|tour|"
        r"full\s+video|entire|every|explore|open\s+(it|the\s+site|the\s+app)|"
        r"go\s+(on|to)\s+the|"
        r"show\s+(me\s+)?(the\s+)?(site|platform|app|ui|interface))\b",
        t,
    ):
        return True
    if re.search(r"\b(video|clip|reel|short|shorts|film|footage)\b", t):
        return True
    if re.search(r"\b(make|create|generate|produce|shoot)\b", t):
        return True
    # Default: named platform in a Mira generate = live tour
    return True


def _wants_quick_tour(text: str) -> bool:
    """True only when user explicitly asks for a short/teaser clip."""
    t = _norm(text)
    return bool(
        re.search(
            r"\b(quick|short|brief|teaser|preview|snippet|30\s*sec|15\s*sec|"
            r"one\s+minute|1\s*min|highlights?\s+only)\b",
            t,
        )
    )


_SPECIFIC_PAGE_RE = re.compile(
    r"\b(pricing|dealflow|airdrop|blog|contact|features|raftai|market|kyc|network|modules)\b",
    re.I,
)


def _step_url_has_page_keyword(step: dict[str, Any], keys: set[str]) -> bool:
    url = str(step.get("url") or "").lower()
    for k in keys:
        if k in url:
            return True
        if k == "raftai" and "raftai" in url:
            return True
        if k == "market" and "market" in url:
            return True
        if k == "modules" and ("module" in url or "features" in url):
            return True
    return False


def _step_matches_page_keywords(step: dict[str, Any], keys: set[str]) -> bool:
    """True when a requested page keyword appears in the step URL or (non-home) narration."""
    if _step_url_has_page_keyword(step, keys):
        return True
    url = str(step.get("url") or "").lower()
    path = (urlparse(url).path or "/").rstrip("/") or "/"
    if path == "/":
        return False
    line = str(step.get("line") or "").lower()
    for k in keys:
        if k in line:
            return True
        if k == "raftai" and "raftai" in line:
            return True
        if k == "market" and "market" in line:
            return True
        if k == "modules" and ("module" in line or "features" in line):
            return True
    return False


def _plan_tour_steps(topic: str, plat: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """Choose which platform URLs to record — quick, selected pages, or capped full tour."""
    notes: list[str] = []
    steps = list(plat.get("steps") or [])

    try:
        from jarvis.mira.platform_session import _filter_steps_by_topic, _topic_exclusions

        before = len(steps)
        excl = _topic_exclusions(topic)
        if excl:
            steps = _filter_steps_by_topic(steps, topic)
            notes.append(f"exclusions={sorted(excl)}")
            notes.append(f"steps_filtered={before}->{len(steps)}")
    except Exception as exc:
        notes.append(f"exclusion_filter_skip:{exc}")

    quick = _wants_quick_tour(topic)
    if quick:
        steps = [dict(s) for s in steps[:1]]
        for s in steps:
            s["dwell_sec"] = min(float(s.get("dwell_sec") or 5.0), 3.5)
            s["max_explore_sec"] = 6.0
            s["scrolls"] = tuple(list(s.get("scrolls") or ())[:3])
        notes.append("tour_mode=quick")
    else:
        t = _norm(topic)
        specific = {m.lower() for m in _SPECIFIC_PAGE_RE.findall(t)}
        selected = False
        if specific:
            filtered = [dict(s) for s in steps if _step_url_has_page_keyword(s, specific)]
            if len(filtered) >= 1:
                steps = filtered
                notes.append("tour_mode=selected_pages")
                selected = True
        if not selected:
            notes.append("tour_mode=full cap=14")
            if len(steps) < 10:
                try:
                    extras = _discover_extra_steps(str(plat.get("home") or ""), steps, limit=3)
                    if extras:
                        steps = list(steps) + extras
                        notes.append(f"discovered_extra_pages={len(extras)}")
                except Exception as exc:
                    notes.append(f"discover_skip:{exc}")
            else:
                notes.append("discover_skip=already_10plus")

    before_u = len(steps)
    steps = _dedupe_steps_one_url(list(steps))
    if len(steps) != before_u:
        notes.append(f"deduped_urls={before_u}->{len(steps)}")

    if not quick and "tour_mode=selected_pages" not in notes and len(steps) > 14:
        steps = steps[:14]
        notes.append("capped_steps=14")

    return steps, notes


def _wants_deep_tour(text: str) -> bool:
    """Default True for platform asks — Owner wants the whole product explained.

    Only skip deep when they explicitly ask for a quick/short clip.
    """
    if _wants_quick_tour(text):
        return False
    t = _norm(text)
    if re.search(
        r"\b(full|entire|complete|every|all|deep|explore|walk\s*through|"
        r"whole|everything|all\s+features|every\s+feature)\b",
        t,
    ):
        return True
    # Named platform video = full tour by default (no artificial limits)
    return True


def _has_playwright() -> bool:
    try:
        import playwright  # noqa: F401

        return True
    except Exception:
        return False


def _wait_page_ready(page: Any, *, max_wait_sec: float = 4.0) -> float:
    """Fast paint check — never block on networkidle (that alone can burn 10s+/page)."""
    t0 = time.time()
    try:
        page.wait_for_load_state("domcontentloaded", timeout=8_000)
    except Exception:
        pass
    try:
        page.wait_for_selector("body", timeout=4_000)
    except Exception:
        pass
    deadline = t0 + max(1.0, float(max_wait_sec))
    while time.time() < deadline:
        try:
            ready = page.evaluate(
                """() => {
                  const b = document.body;
                  if (!b) return false;
                  const textLen = (b.innerText || '').trim().length;
                  const kids = b.querySelectorAll('img,video,canvas,h1,h2,p,a,button,nav,main,section').length;
                  if (textLen < 40 && kids < 6) return false;
                  return textLen >= 40 || kids >= 8;
                }"""
            )
            if ready:
                page.wait_for_timeout(200)
                return max(0.2, time.time() - t0)
        except Exception:
            pass
        page.wait_for_timeout(120)
    return max(0.4, time.time() - t0)


def _dismiss_blocking_overlays(page: Any) -> str:
    """Accept/Decline/Close cookie, consent, and ad banners that block the screen tour.

    Owner wants a clear view of the platform — either Accept or Decline is fine;
    we just must remove the overlay before recording/scrolling.
    """
    if page is None:
        return "skip"
    actions: list[str] = []

    # 1) Role/name buttons (CryptoRafts "Cookies & ads", OneTrust, Cookiebot, etc.)
    click_names = (
        "Decline",
        "Reject",
        "Reject all",
        "Reject All",
        "Refuse",
        "Necessary only",
        "Only necessary",
        "Accept",
        "Accept all",
        "Accept All",
        "Allow all",
        "Allow All",
        "Agree",
        "I agree",
        "Got it",
        "OK",
        "Okay",
        "Close",
    )
    for name in click_names:
        try:
            loc = page.get_by_role("button", name=re.compile(rf"^\s*{re.escape(name)}\s*$", re.I))
            if loc.count() > 0:
                loc.first.click(timeout=900)
                actions.append(f"btn:{name}")
                page.wait_for_timeout(180)
                break
        except Exception:
            continue

    # 2) Common consent SDK selectors
    css_click = (
        "#onetrust-reject-all-handler",
        "#onetrust-accept-btn-handler",
        ".onetrust-close-btn-handler",
        "#accept-recommended-btn-handler",
        "button#accept-cookie",
        "button#cookie-accept",
        "button[aria-label*='Accept' i]",
        "button[aria-label*='Decline' i]",
        "button[aria-label*='Reject' i]",
        "button[aria-label*='Close' i]",
        "[data-testid*='cookie'] button",
        ".cc-btn.cc-dismiss",
        ".cc-allow",
        ".cc-deny",
        "#CybotCookiebotDialogBodyButtonDecline",
        "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
        ".fc-cta-consent",
        ".fc-cta-do-not-consent",
    )
    if not actions:
        for sel in css_click:
            try:
                loc = page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    loc.first.click(timeout=900)
                    actions.append(f"css:{sel}")
                    page.wait_for_timeout(180)
                    break
            except Exception:
                continue

    # 3) Text match inside banner (CryptoRafts: Accept / Decline)
    if not actions:
        try:
            for label in ("Decline", "Reject", "Accept", "Agree", "Got it"):
                loc = page.locator(
                    f"button:has-text('{label}'), a:has-text('{label}'), "
                    f"[role='button']:has-text('{label}')"
                )
                if loc.count() > 0:
                    loc.first.click(timeout=900)
                    actions.append(f"text:{label}")
                    page.wait_for_timeout(180)
                    break
        except Exception:
            pass

    # 3b) DOM walk — click first matching consent button by label text
    if not actions:
        try:
            clicked = page.evaluate(
                """() => {
                  const want = /^(decline|reject|reject all|accept|accept all|agree|got it|ok|okay|close|allow all|necessary only)$/i;
                  const nodes = Array.from(document.querySelectorAll(
                    'button, a, [role="button"], input[type="button"], input[type="submit"]'
                  ));
                  for (const el of nodes) {
                    const label = ((el.innerText || el.value || el.getAttribute('aria-label') || '')).trim();
                    if (!want.test(label)) continue;
                    try { el.click(); return label; } catch (e) {}
                  }
                  return '';
                }"""
            )
            if clicked:
                actions.append(f"dom:{clicked}")
                page.wait_for_timeout(180)
        except Exception:
            pass

    # 4) Nuclear hide — leftover cookie/CMP only (never bare "consent"/"privacy" — blanks Gemini)
    try:
        hidden = page.evaluate(
            """() => {
              const keys = /cookies?\\s*&\\s*ads|we use cookies|cookiebot|onetrust|cookie policy|accept cookies|reject all|personalized ads|gdpr cookie|Cookies\\s*&\\s*ads/i;
              let n = 0;
              const nodes = Array.from(document.querySelectorAll(
                '[id*="onetrust" i], [id*="cookiebot" i], [class*="cookie-banner" i], [class*="CookieBanner" i], dialog, [role="dialog"], [role="alertdialog"]'
              ));
              for (const el of nodes) {
                try {
                  if (el === document.body || el === document.documentElement) continue;
                  if (el.querySelector('main, [role="main"], textarea, input[type="text"], input[type="search"]')) continue;
                  const txt = ((el.innerText || '') + ' ' + (el.className || '') + ' ' + (el.id || '')).slice(0, 500);
                  if (!keys.test(txt)) continue;
                  const r = el.getBoundingClientRect();
                  if (r.width < 120 || r.height < 60) continue;
                  // Never hide near-fullscreen app shells
                  if (r.height > window.innerHeight * 0.85 && r.width > window.innerWidth * 0.85) continue;
                  const style = window.getComputedStyle(el);
                  const fixed = style.position === 'fixed' || style.position === 'sticky';
                  const covers = r.height > window.innerHeight * 0.15 || r.width > window.innerWidth * 0.35;
                  if (fixed || covers) {
                    el.style.setProperty('display', 'none', 'important');
                    el.style.setProperty('visibility', 'hidden', 'important');
                    el.style.setProperty('pointer-events', 'none', 'important');
                    el.setAttribute('data-mira-dismissed', '1');
                    n++;
                  }
                } catch (e) {}
              }
              try {
                document.documentElement.style.overflow = 'auto';
                if (document.body) {
                  document.body.style.overflow = 'auto';
                  document.body.style.opacity = '1';
                  document.body.style.visibility = 'visible';
                }
              } catch (e) {}
              return n;
            }"""
        )
        if hidden:
            actions.append(f"hide:{hidden}")
    except Exception:
        pass

    return ",".join(actions) if actions else "none"


def _dedupe_steps_one_url(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each unique page opens once — merge duplicate URLs into one full scroll + VO.

    Unless the step sets allow_repeat=True (Owner asked to open it twice).
    """
    out: list[dict[str, Any]] = []
    by_key: dict[str, int] = {}
    for step in steps:
        if step.get("allow_repeat"):
            out.append(dict(step))
            continue
        url = str(step.get("url") or "").strip().split("#")[0].split("?")[0].rstrip("/") or "/"
        key = url.lower()
        if key in by_key:
            prev = out[by_key[key]]
            # Merge scrolls (full page pass) and join narration
            scrolls = list(prev.get("scrolls") or ())
            for y in step.get("scrolls") or ():
                try:
                    yi = int(y)
                except Exception:
                    continue
                if yi not in scrolls:
                    scrolls.append(yi)
            scrolls = sorted(set(int(x) for x in scrolls))
            prev["scrolls"] = tuple(scrolls)
            line_a = str(prev.get("line") or "").strip()
            line_b = str(step.get("line") or "").strip()
            if line_b and line_b not in line_a:
                prev["line"] = f"{line_a} {line_b}".strip() if line_a else line_b
            prev["dwell_sec"] = max(
                float(prev.get("dwell_sec") or 4.0),
                float(step.get("dwell_sec") or 4.0),
                6.0,
            )
            continue
        by_key[key] = len(out)
        out.append(dict(step))
    return out


def _full_page_scrolls(page: Any) -> list[int]:
    """Build scroll targets covering the entire document once."""
    try:
        h = int(
            page.evaluate(
                """() => Math.max(
                  document.body ? document.body.scrollHeight : 0,
                  document.documentElement ? document.documentElement.scrollHeight : 0,
                  2400
                )"""
            )
            or 2400
        )
    except Exception:
        h = 3200
    h = max(1800, min(h, 14000))
    # ~5–8 stops down the page so VO can explain as we go
    n = 6 if h < 5000 else (8 if h < 9000 else 10)
    step = max(350, h // n)
    targets = [0]
    y = step
    while y < h - 200:
        targets.append(int(y))
        y += step
    targets.append(max(0, h - 80))
    return targets


def _explore_page(page: Any, step: dict[str, Any]) -> None:
    """Smooth-scroll the FULL page once and dwell so VO can explain features."""
    import time as _time

    t0 = _time.time()
    max_sec = max(2.5, min(18.0, float(step.get("max_explore_sec") or 12.0)))
    # Always prefer live document height so long feature pages are fully explored
    targets = _full_page_scrolls(page)
    if step.get("scrolls"):
        # Keep any explicit deep anchors, then cover the rest of the page
        extra = [max(0, int(y)) for y in (step.get("scrolls") or ())]
        targets = sorted(set(targets + extra))
    # Cap scroll stops so one tall page can't hang the whole tour
    if len(targets) > 10:
        first, last = targets[0], targets[-1]
        mid = targets[1:-1]
        step_i = max(1, len(mid) // 8) if mid else 1
        targets = [first] + mid[::step_i][:8] + [last]
        targets = sorted(set(targets))
    dwell = max(3.0, min(12.0, float(step.get("dwell_sec") or 7.0)))
    per = max(0.4, dwell / max(1, len(targets)))
    # Keep UI opaque — do NOT force navy fill (breaks light pages like Gemini)
    try:
        page.evaluate(
            """() => {
              if (document.body) {
                document.body.style.opacity = '1';
                document.body.style.visibility = 'visible';
              }
            }"""
        )
    except Exception:
        pass
    page.wait_for_timeout(200)
    prev = 0
    for y in targets:
        if (_time.time() - t0) >= max_sec:
            break
        steps_n = max(3, min(8, abs(y - prev) // 140 or 3))
        for s in range(1, steps_n + 1):
            if (_time.time() - t0) >= max_sec:
                break
            mid = int(prev + (y - prev) * (s / steps_n))
            try:
                page.evaluate(f"window.scrollTo(0, {mid})")
            except Exception:
                break
            page.wait_for_timeout(int((per * 1000) / steps_n))
        prev = y
        page.wait_for_timeout(60)


def _install_dark_boot(context: Any) -> None:
    """Soft dark shell while loading — never hide UI (opacity 0 = black video).

    Do NOT force a navy fill on every site: Google 404 / light pages looked blank.
    """
    try:
        context.add_init_script(
            """
            (() => {
              const paint = () => {
                try {
                  const body = document.body;
                  if (body) {
                    body.style.opacity = '1';
                    body.style.visibility = 'visible';
                  }
                  if (document.documentElement) {
                    document.documentElement.style.opacity = '1';
                    document.documentElement.style.visibility = 'visible';
                  }
                } catch (e) {}
              };
              paint();
              document.addEventListener('DOMContentLoaded', paint);

              const killCookies = () => {
                try {
                  if (window.__miraCookieDone) return;
                  // Strict: only real cookie/CMP banners — never bare "consent" (hides Gemini UI)
                  const keys = /cookies?\\s*&\\s*ads|we use cookies|cookiebot|onetrust|cookie policy|accept cookies|reject all|personalized ads|gdpr cookie/i;
                  const btnWant = /^(decline|reject|reject all|accept|accept all|agree|got it|ok|okay|close|allow all|necessary only)$/i;
                  const btns = Array.from(document.querySelectorAll(
                    'button, a, [role="button"], input[type="button"]'
                  ));
                  for (const b of btns) {
                    const label = ((b.innerText || b.value || b.getAttribute('aria-label') || '')).trim();
                    if (!btnWant.test(label)) continue;
                    const root = b.closest('div,section,aside,dialog,[role="dialog"]') || b.parentElement;
                    const blob = ((root && root.innerText) || label || '').slice(0, 400);
                    if (keys.test(blob) || /Cookies\\s*&\\s*ads/i.test(blob)) {
                      try { b.click(); } catch (e) {}
                      break;
                    }
                  }
                  let killed = 0;
                  const nodes = Array.from(document.querySelectorAll(
                    '[id*="onetrust" i], [id*="cookiebot" i], [class*="cookie-banner" i], [class*="CookieBanner" i], [aria-label*="cookie" i], dialog, [role="dialog"], [role="alertdialog"]'
                  ));
                  for (const el of nodes) {
                    if (el.getAttribute('data-mira-cookie-killed')) continue;
                    const txt = ((el.innerText || '') + ' ' + (el.id || '') + ' ' + (el.className || '')).slice(0, 600);
                    if (!keys.test(txt) && !/Cookies\\s*&\\s*ads/i.test(txt)) continue;
                    // Never hide the main app shell
                    if (el === document.body || el === document.documentElement) continue;
                    if (el.querySelector('main, [role="main"], textarea, input[type="text"]')) continue;
                    const r = el.getBoundingClientRect();
                    if (r.width < 80 || r.height < 40) continue;
                    if (r.height > window.innerHeight * 0.85 && r.width > window.innerWidth * 0.85) continue;
                    el.style.setProperty('display', 'none', 'important');
                    el.style.setProperty('visibility', 'hidden', 'important');
                    el.style.setProperty('pointer-events', 'none', 'important');
                    el.setAttribute('data-mira-cookie-killed', '1');
                    killed++;
                  }
                  document.documentElement.style.overflow = 'auto';
                  if (document.body) {
                    document.body.style.overflow = 'auto';
                    document.body.style.opacity = '1';
                  }
                  if (killed > 0) window.__miraCookieDone = true;
                } catch (e) {}
              };
              const arm = () => {
                killCookies();
                setTimeout(killCookies, 500);
                setTimeout(killCookies, 1500);
              };
              if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', arm);
              } else {
                arm();
              }
            })();
            """
        )
    except Exception:
        pass


def _force_visible_ui(page: Any) -> None:
    """Ensure recorded frames are not blank — undo opacity tricks and unlock scroll."""
    try:
        page.evaluate(
            """() => {
              const show = (el) => {
                if (!el || !el.style) return;
                el.style.setProperty('opacity', '1', 'important');
                el.style.setProperty('visibility', 'visible', 'important');
              };
              show(document.documentElement);
              show(document.body);
              // Un-hide accidental full-page kills
              document.querySelectorAll('[data-mira-cookie-killed]').forEach((el) => {
                const r = el.getBoundingClientRect();
                if (r.height > window.innerHeight * 0.7 && r.width > window.innerWidth * 0.7) {
                  el.style.removeProperty('display');
                  el.style.removeProperty('visibility');
                  el.style.removeProperty('opacity');
                  el.removeAttribute('data-mira-cookie-killed');
                }
              });
            }"""
        )
    except Exception:
        pass


def _page_looks_blank(page: Any) -> bool:
    """True when the viewport has almost no readable UI (black/empty/404 record risk)."""
    try:
        return bool(
            page.evaluate(
                """() => {
                  const b = document.body;
                  if (!b) return true;
                  const t = (b.innerText || '').replace(/\\s+/g, ' ').trim();
                  const low = t.toLowerCase();
                  // Dead ends — never record Google/generic 404 shells as a "tour"
                  if (/\\b404\\b/.test(low) && /error|not found|requested url/i.test(low)) return true;
                  if (/page not found|this page (doesn.t|does not) exist|couldn.t find/i.test(low) && t.length < 400) return true;
                  const kids = b.querySelectorAll('img,video,canvas,button,a,input,textarea,h1,h2,p,nav,main').length;
                  const op = parseFloat(getComputedStyle(b).opacity || '1');
                  if (op < 0.2) return true;
                  return t.length < 30 && kids < 5;
                }"""
            )
        )
    except Exception:
        return True


def _screenshot_mean_luminance(page: Any) -> float:
    """Viewport screenshot mean RGB — catches headless pages that pass DOM blank checks."""
    stats = _screenshot_stats(page)
    return stats[0]


def _screenshot_stats(page: Any) -> tuple[float, float]:
    """Return (mean_luminance, mean_channel_spread) for the viewport."""
    try:
        raw = page.screenshot(type="jpeg", quality=45, full_page=False)
        from PIL import Image
        import io

        im = Image.open(io.BytesIO(raw)).convert("RGB")
        im.thumbnail((360, 360))
        px = list(im.getdata())
        if not px:
            return 0.0, 0.0
        lums = [(r + g + b) / 3.0 for r, g, b in px]
        spreads = [max(p) - min(p) for p in px]
        return sum(lums) / len(lums), sum(spreads) / len(spreads)
    except Exception:
        return 0.0, 0.0


def _screenshot_looks_recordable(page: Any) -> bool:
    """Reject Chromium's flat blue/navy BOOT only — dark themed sites (CryptoRafts) are OK.

    Boot = almost one solid color (very low channel spread < ~4).
    Real dark UI has text/buttons → higher spread even when mean luminance is low.
    """
    mean_lum, spread = _screenshot_stats(page)
    if mean_lum < 2 and spread < 2:
        return False
    if mean_lum > 248 and spread < 10:
        return False
    # Flat blue boot plate only (Owner's empty "blue page")
    if spread < 4.0 and mean_lum < 40:
        return False
    return True


def _wait_for_painted_ui(
    page: Any,
    *,
    min_wait_sec: float = 10.0,
    max_wait_sec: float = 20.0,
    progress_cb: Any | None = None,
) -> bool:
    """Owner rule: wait 10–20s for the real page to finish loading before any screen-record."""
    t0 = time.time()
    min_w = max(8.0, float(min_wait_sec))
    max_w = max(min_w, min(22.0, float(max_wait_sec)))
    deadline = t0 + max_w
    last_note = 0.0
    while time.time() < deadline:
        elapsed = time.time() - t0
        if progress_cb and (elapsed - last_note) >= 3.0:
            last_note = elapsed
            try:
                progress_cb(f"Waiting for page to finish loading… {int(min(elapsed, max_w))}s / {int(max_w)}s")
            except Exception:
                pass
        try:
            _dismiss_blocking_overlays(page)
        except Exception:
            pass
        try:
            _force_visible_ui(page)
        except Exception:
            pass
        try:
            blank = _page_looks_blank(page)
        except Exception:
            blank = True
        try:
            painted = (not blank) and _screenshot_looks_recordable(page)
        except Exception:
            painted = False
        if painted and elapsed >= min_w:
            return True
        if elapsed >= min_w and not blank:
            try:
                _lum, spread = _screenshot_stats(page)
            except Exception:
                spread = 0.0
            if spread >= 4.0:
                return True
        remain_ms = int(max(50, (deadline - time.time()) * 1000))
        try:
            page.wait_for_timeout(min(500, remain_ms))
        except Exception:
            break
    # Final decision at deadline
    try:
        if not _page_looks_blank(page):
            _lum, spread = _screenshot_stats(page)
            return spread >= 3.5 or _screenshot_looks_recordable(page)
    except Exception:
        pass
    return False


def _frames_dir_to_mp4(frames_dir: Path, dest: Path, *, fps: int = 6) -> Path | None:
    """Build an mp4 from sequential JPEG screenshots (reliable when Playwright video is blue)."""
    import imageio_ffmpeg
    import subprocess

    frames = sorted(frames_dir.glob("frame_*.jpg"))
    if len(frames) < 4:
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    # Numbered sequence avoids Windows path / concat demuxer issues
    for i, fr in enumerate(frames):
        seq = frames_dir / f"seq_{i + 1:04d}.jpg"
        if seq.resolve() != fr.resolve():
            try:
                shutil.copy2(fr, seq)
            except Exception:
                seq.write_bytes(fr.read_bytes())
    # ~2 stills/sec → 12 frames ≈ 6s; stretch with -r out 30
    in_rate = max(1.0, min(3.0, len(frames) / 10.0))
    pattern = str((frames_dir / "seq_%04d.jpg").resolve())
    cmd = [
        ff,
        "-y",
        "-framerate",
        f"{in_rate:.3f}",
        "-i",
        pattern,
        "-vf",
        "fps=30,format=yuv420p",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(dest),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if proc.returncode == 0 and dest.is_file() and dest.stat().st_size > 30_000:
            return dest.resolve()
        logger.warning("frames_to_mp4 ffmpeg rc=%s err=%s", proc.returncode, (proc.stderr or "")[-300:])
    except Exception as exc:
        logger.warning("frames_to_mp4 failed: %s", exc)
    return None


def _record_step_via_screenshots(
    page: Any,
    step: dict[str, Any],
    clips_dir: Path,
    *,
    index: int,
    platform_id: str = "",
    deep_demo: bool = False,
    progress_cb: Any | None = None,
) -> tuple[Path | None, float]:
    """After 10–20s warm load: dismiss cookies, scroll, grab stills → real UI mp4."""
    frames_dir = clips_dir / f"_frames_{index}_{uuid.uuid4().hex[:6]}"
    frames_dir.mkdir(parents=True, exist_ok=True)
    n = 0

    def _snap() -> None:
        nonlocal n
        try:
            shot = page.screenshot(type="jpeg", quality=72, full_page=False)
            (frames_dir / f"frame_{n:04d}.jpg").write_bytes(shot)
            n += 1
        except Exception:
            pass

    try:
        try:
            _dismiss_blocking_overlays(page)
        except Exception:
            pass
        _force_visible_ui(page)
        page.wait_for_timeout(400)
        try:
            _dismiss_blocking_overlays(page)
        except Exception:
            pass

        if deep_demo and platform_id:
            from jarvis.mira.demo_actions import run_demo_actions

            step_url = str(step.get("url") or "")
            demo_notes = run_demo_actions(
                page,
                platform_id,
                step_url,
                progress_cb=progress_cb,
                on_frame=_snap,
                max_sec=14.0,
            )
            step["demo_notes"] = demo_notes
            typed = any(str(note).startswith("demo_type") for note in demo_notes)
            if typed:
                line = str(step.get("line") or "").strip()
                extra = (
                    " Mira is using the live UI here — typing and interacting with what you see on screen."
                )
                if extra.strip() not in line:
                    step["line"] = f"{line}{extra}".strip() if line else extra.strip()

        dwell = min(12.0, max(3.0, float(step.get("dwell_sec") or 9.0)))
        t0 = time.time()
        targets = _full_page_scrolls(page)
        if step.get("scrolls"):
            targets = sorted(set(targets + [max(0, int(y)) for y in (step.get("scrolls") or ())]))
        if len(targets) < 10:
            hi = max(targets[-1] if targets else 2000, 2000)
            targets = sorted(set(list(targets) + list(range(0, hi + 1, max(150, hi // 12)))))
        max_stops = int(step.get("max_scroll_stops") or 20)
        if len(targets) > max_stops:
            targets = targets[:: max(1, len(targets) // max_stops)][:max_stops]
        if not targets:
            targets = list(range(0, 2401, 200))
        per = dwell / max(1, len(targets))
        for y in targets:
            if (time.time() - t0) >= dwell + 2.0:
                break
            try:
                page.evaluate(f"window.scrollTo(0, {int(y)})")
            except Exception:
                pass
            page.wait_for_timeout(int(max(280, per * 1000)))
            _snap()
        while n < 12 and (time.time() - t0) < dwell + 4.0:
            _snap()
            if n >= 12:
                break
            page.wait_for_timeout(350)
        if n < 4:
            logger.warning("too few screenshot frames: %s", n)
            return None, 0.0
        dest = clips_dir / f"platform_{index}_{uuid.uuid4().hex[:6]}.mp4"
        out = _frames_dir_to_mp4(frames_dir, dest, fps=2)
        if out and out.is_file() and out.stat().st_size > 40_000:
            return out, 0.0
        logger.warning("screenshot mp4 missing or tiny (frames=%s)", n)
        return None, 0.0
    finally:
        shutil.rmtree(frames_dir, ignore_errors=True)


def _verify_mp4_has_ui(path: Path, *, at_sec: float = 1.0) -> bool:
    """Sample one encoded frame — reject only flat boot plates, not dark themed UIs."""
    import imageio_ffmpeg
    import subprocess
    from PIL import Image
    import io

    if not path.is_file() or path.stat().st_size < 20_000:
        return False
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    raw = subprocess.run(
        [
            ff,
            "-y",
            "-ss",
            f"{max(0.2, at_sec):.2f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "mjpeg",
            "pipe:1",
        ],
        capture_output=True,
        timeout=45,
    )
    if raw.returncode != 0 or not raw.stdout:
        return False
    im = Image.open(io.BytesIO(raw.stdout)).convert("RGB")
    im.thumbnail((360, 360))
    px = list(im.getdata())
    if not px:
        return False
    lums = [(r + g + b) / 3.0 for r, g, b in px]
    spreads = [max(p) - min(p) for p in px]
    mean_lum = sum(lums) / len(lums)
    spread = sum(spreads) / len(spreads)
    if mean_lum < 2 and spread < 2:
        return False
    if mean_lum > 248 and spread < 10:
        return False
    if spread < 4.0 and mean_lum < 40:
        return False
    return True


def _media_duration_sec(path: Path) -> float:
    import imageio_ffmpeg
    import subprocess

    ff = imageio_ffmpeg.get_ffmpeg_exe()
    proc = subprocess.run(
        [ff, "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
        timeout=45,
    )
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", proc.stderr or "")
    if not m:
        return 0.0
    h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return h * 3600 + mi * 60 + s


def _cookie_banner_visible(page: Any) -> bool:
    """True if a Cookies & ads / consent overlay is still covering the view."""
    try:
        return bool(
            page.evaluate(
                """() => {
                  const keys = /Cookies\\s*&\\s*ads|cookie|consent|personalized ads|AdSense/i;
                  const nodes = Array.from(document.querySelectorAll(
                    'div,section,aside,dialog,[role="dialog"],[role="alertdialog"]'
                  ));
                  for (const el of nodes) {
                    if (el.getAttribute('data-mira-cookie-killed')) continue;
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') continue;
                    const txt = (el.innerText || '').slice(0, 400);
                    if (!keys.test(txt)) continue;
                    const r = el.getBoundingClientRect();
                    if (r.width > 160 && r.height > 60) return true;
                  }
                  return false;
                }"""
            )
        )
    except Exception:
        return False


def _record_step_clip(
    step: dict[str, Any],
    clips_dir: Path,
    *,
    width: int,
    height: int,
    index: int,
) -> tuple[Path | None, float]:
    """Open one platform URL and save a Playwright video of the real UI.

    Warm-loads first (no record) so the recorded take starts on painted content.
    Returns (path, trim_start_sec) — trim is capped small (no more 17s cuts).
    """
    clips = _record_tour_clips(
        [step],
        clips_dir,
        width=width,
        height=height,
        index_base=index,
    )
    if not clips:
        return None, 0.0
    return clips[0][0], clips[0][1]


def _split_webm_segments(
    src: Path,
    segments: list[tuple[float, float, dict[str, Any]]],
    clips_dir: Path,
    *,
    index_base: int = 0,
) -> list[tuple[Path, float, dict[str, Any]]]:
    """Cut one continuous Playwright webm into per-step clips (start_sec, duration_sec, step)."""
    import imageio_ffmpeg
    import subprocess

    if not src.is_file() or src.stat().st_size < 4_000:
        return []
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    out: list[tuple[Path, float, dict[str, Any]]] = []
    for i, (start, dur, step) in enumerate(segments):
        if dur < 0.8:
            continue
        idx = index_base + i
        dest = clips_dir / f"platform_{idx}_{uuid.uuid4().hex[:6]}.webm"
        trim_in = max(0.0, float(start))
        cmd = [
            ff,
            "-y",
            "-ss",
            f"{trim_in:.3f}",
            "-i",
            str(src),
            "-t",
            f"{dur:.3f}",
            "-c",
            "copy",
            str(dest),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
            if proc.returncode != 0 or not dest.is_file() or dest.stat().st_size < 8_000:
                continue
            out.append((dest.resolve(), 0.2, step))
        except Exception as exc:
            logger.warning("split segment %s failed: %s", i, exc)
    return out


def _record_tour_clips(
    steps: list[dict[str, Any]],
    clips_dir: Path,
    *,
    width: int,
    height: int,
    index_base: int = 0,
    platform_id: str = "",
    deep_demo: bool = False,
    progress_cb: Any | None = None,
) -> list[tuple[Path, float, dict[str, Any]]]:
    """Warm-load each page 10–20s (no video), THEN screen-record only painted UI.

    Continuous record-from-t0 captured Chromium's solid blue/navy boot while apps
    were still loading. Owner asked to wait for the page first, then record.
    """
    from playwright.sync_api import sync_playwright

    clips_dir.mkdir(parents=True, exist_ok=True)
    out: list[tuple[Path, float, dict[str, Any]]] = []
    if not steps:
        return out

    def _prog(msg: str) -> None:
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass
        try:
            from jarvis.tools.mira_jobs import set_progress

            set_progress(msg)
        except Exception:
            pass

    work_root = clips_dir / f"_tour_{uuid.uuid4().hex[:8]}"
    work_root.mkdir(parents=True, exist_ok=True)
    ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )

    def _goto_best(page: Any, url: str, fallbacks: tuple[str, ...] = ()) -> str | None:
        for cand in (url,) + tuple(fallbacks):
            cand = str(cand or "").strip()
            if not cand:
                continue
            ok = False
            for wait_until, nav_timeout in (
                ("domcontentloaded", 20_000),
                ("commit", 12_000),
                ("load", 18_000),
            ):
                try:
                    page.goto(cand, wait_until=wait_until, timeout=nav_timeout)
                    ok = True
                    break
                except Exception as exc:
                    logger.debug("goto %s %s: %s", wait_until, cand, exc)
            if ok:
                return cand
        return None

    per_step_deadline_sec = 48.0 if deep_demo else 35.0
    compact_tour = len(steps) > 6

    try:
        # Screenshot capture works in headless; headed only needed for broken WebM path.
        record_headless = True
        try:
            import os

            h = str(os.environ.get("MIRA_RECORD_HEADLESS") or "").strip().lower()
            if h in ("0", "false", "no"):
                record_headless = False
            elif h in ("1", "true", "yes"):
                record_headless = True
        except Exception:
            pass

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=record_headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--autoplay-policy=no-user-gesture-required",
                ],
            )
            n_steps = len(steps)
            ctx = browser.new_context(
                viewport={"width": width, "height": height},
                user_agent=ua,
            )
            _install_dark_boot(ctx)
            page = ctx.new_page()
            try:
                page.set_default_timeout(15_000)
                page.set_default_navigation_timeout(20_000)
            except Exception:
                pass

            for i, step in enumerate(steps):
                url = str(step.get("url") or "").strip()
                if not url:
                    continue
                idx = index_base + i
                short = str(step.get("line") or url)[:70]
                fallbacks = tuple(
                    str(u).strip() for u in (step.get("fallback_urls") or ()) if str(u).strip()
                )
                step_t0 = time.time()

                def _step_time_left() -> float:
                    return per_step_deadline_sec - (time.time() - step_t0)

                _prog(f"Page {i + 1}/{n_steps}: loading… {short}")

                loaded = None
                try:
                    loaded = _goto_best(page, url, fallbacks)
                    if not loaded:
                        logger.warning("goto failed: %s", url)
                        continue

                    min_w = 8.0 if i == 0 else 2.5
                    max_w = min(14.0 if i == 0 else 7.0, max(1.0, _step_time_left() - 8.0))
                    if max_w < min_w:
                        logger.warning("step timeout budget exhausted before wait url=%s", loaded)
                        continue

                    _prog(f"Page {i + 1}/{n_steps}: waiting for UI…")
                    painted = _wait_for_painted_ui(
                        page,
                        min_wait_sec=min_w,
                        max_wait_sec=max_w,
                        progress_cb=_prog,
                    )
                    if not painted and _step_time_left() < 3.0:
                        logger.warning("step timeout after wait url=%s", loaded)
                        continue
                    if not painted:
                        lum, spread = _screenshot_stats(page)
                        logger.warning(
                            "page never painted (skip record) url=%s lum=%.1f spread=%.1f",
                            loaded,
                            lum,
                            spread,
                        )
                        continue

                    _prog(f"Recording live {i + 1}/{n_steps}: {short}")
                    step_explore = dict(step)
                    step_explore["url"] = loaded
                    if compact_tour:
                        step_explore["dwell_sec"] = min(
                            5.5, float(step_explore.get("dwell_sec") or 5.5)
                        )
                        scrolls = list(step_explore.get("scrolls") or ())
                        step_explore["scrolls"] = tuple(scrolls[:4])
                        step_explore["max_scroll_stops"] = 10

                    clip_path, trim = _record_step_via_screenshots(
                        page,
                        step_explore,
                        clips_dir,
                        index=idx,
                        platform_id=platform_id,
                        deep_demo=deep_demo,
                        progress_cb=progress_cb,
                    )
                    if clip_path:
                        out.append((Path(clip_path).resolve(), trim, step_explore))
                    if _step_time_left() <= 0:
                        logger.warning("step exceeded %ss wall clock url=%s", per_step_deadline_sec, loaded)
                except Exception as exc:
                    logger.exception("record step failed %s: %s", url, exc)
                    continue

            try:
                ctx.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass
    except Exception as exc:
        logger.exception("tour session failed: %s", exc)
    finally:
        shutil.rmtree(work_root, ignore_errors=True)
    return out


def _webm_to_mp4(src: Path, dest: Path, *, trim_start_sec: float = 0.0) -> Path:
    """Convert Playwright webm → smooth mp4; lightly trim remaining load flash."""
    import imageio_ffmpeg
    import subprocess

    ff = imageio_ffmpeg.get_ffmpeg_exe()
    dest.parent.mkdir(parents=True, exist_ok=True)
    trim = min(3.2, max(0.0, float(trim_start_sec or 0.0)))
    dur = _media_duration_sec(src)
    if dur > 0.5:
        trim = min(trim, max(0.0, dur - 0.4))
        if trim >= dur - 0.15:
            trim = 0.0
    cmd = [ff, "-y"]
    if trim >= 0.15:
        cmd.extend(["-ss", f"{trim:.2f}"])
    # Soft fade so hard cuts between pages never flash white
    cmd.extend(
        [
            "-i",
            str(src),
            "-vf",
            "fade=t=in:st=0:d=0.35,fps=30,format=yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "30",
            "-an",
            str(dest),
        ]
    )
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0 or not dest.is_file() or dest.stat().st_size < 4000:
        # Retry without fancy fade if filter graph failed
        cmd2 = [ff, "-y"]
        if trim >= 0.15:
            cmd2.extend(["-ss", f"{trim:.2f}"])
        cmd2.extend(
            [
                "-i",
                str(src),
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-r",
                "30",
                "-an",
                str(dest),
            ]
        )
        proc2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=120)
        if proc2.returncode != 0 or not dest.is_file() or dest.stat().st_size < 4000:
            if trim >= 0.15:
                return _webm_to_mp4(src, dest, trim_start_sec=0.0)
            err = (proc.stderr or proc2.stderr or "")[-400:]
            raise RuntimeError(f"webm→mp4 failed: {err}")
    return dest.resolve()


def _discover_extra_steps(home: str, existing: list[dict[str, Any]], *, limit: int = 3) -> list[dict[str, Any]]:
    """Optionally discover a few same-site nav links for deeper tours."""
    if not home or not _has_playwright():
        return []
    from playwright.sync_api import sync_playwright

    seen = {str(s.get("url") or "").rstrip("/") for s in existing}
    extras: list[dict[str, Any]] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(home, wait_until="domcontentloaded", timeout=40_000)
            _wait_page_ready(page, max_wait_sec=12.0)
            hrefs = page.eval_on_selector_all(
                "a[href]",
                "els => els.map(e => e.href).filter(Boolean)",
            )
            browser.close()
    except Exception as exc:
        logger.warning("link discover failed: %s", exc)
        return []

    host = urlparse(home).netloc
    prefer = (
        "feature",
        "product",
        "pricing",
        "docs",
        "whitepaper",
        "about",
        "network",
        "deal",
        "explore",
        "blog",
        "security",
        "ai",
    )
    ranked: list[tuple[int, str]] = []
    for href in hrefs or []:
        try:
            full = urljoin(home, str(href))
            p = urlparse(full)
            if p.netloc != host:
                continue
            path = (p.path or "/").rstrip("/") or "/"
            if path in ("/", "") or full.rstrip("/") in seen:
                continue
            if any(
                x in path.lower()
                for x in (
                    "login",
                    "signup",
                    "sign-in",
                    "register",
                    "auth",
                    "cart",
                    "cookie",
                    "privacy",
                    "terms",
                )
            ):
                continue
            score = 0
            low = path.lower()
            for i, key in enumerate(prefer):
                if key in low:
                    score = 100 - i
                    break
            if score <= 0 and len(path) > 1:
                score = 5
            if score > 0:
                ranked.append((score, full.split("#")[0].split("?")[0]))
        except Exception:
            continue
    ranked.sort(key=lambda x: -x[0])
    for _score, url in ranked:
        if url.rstrip("/") in seen:
            continue
        seen.add(url.rstrip("/"))
        leaf = urlparse(url).path.strip("/").replace("-", " ").replace("/", " ") or "page"
        extras.append(
            {
                "url": url,
                "dwell_sec": 5.0,
                "scrolls": (500, 1100, 1700),
                "line": f"Next we open {leaf} on the platform and look through what this page offers.",
            }
        )
        if len(extras) >= limit:
            break
    return extras


def run_platform_tour(
    topic: str,
    *,
    duration_sec: int = 45,
    aspect: str = "16:9",
    voice: str | None = None,
    audio_mode: str = "voice",
    out_root: Path | None = None,
    progress_cb: Any | None = None,
) -> dict[str, Any]:
    """Record a platform tour — prefer signed-in continuous session when possible."""
    notes: list[str] = ["mode=platform_screen_record_v4"]

    def _p(msg: str) -> None:
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass
        try:
            from jarvis.tools.mira_jobs import set_progress

            set_progress(msg)
        except Exception:
            pass

    plat = detect_platform(topic)
    if not plat:
        return {"ok": False, "status": "error", "message": "No known platform in ask", "notes": notes}
    if not _has_playwright():
        return {
            "ok": False,
            "status": "error",
            "message": "Playwright missing — run: pip install playwright && playwright install chromium",
            "notes": notes,
        }

    _p(f"Opening {plat['name']} live — screen recording…")

    # Skip flaky continuous webm — go straight to live multi-clip screen-record
    # (real CryptoRafts/HF/… pages). Continuous path kept as optional fast path.
    prefer_continuous = False
    try:
        import os

        prefer_continuous = str(os.environ.get("MIRA_CONTINUOUS_TOUR") or "").strip() in (
            "1",
            "true",
            "yes",
        )
    except Exception:
        prefer_continuous = False

    if prefer_continuous:
        try:
            from jarvis.mira.platform_session import auth_spec, run_signed_continuous_tour

            if auth_spec(plat["id"]):
                signed = run_signed_continuous_tour(
                    plat["id"],
                    plat["name"],
                    topic=topic,
                    aspect=aspect,
                    voice=voice,
                    audio_mode=audio_mode,
                    out_root=out_root,
                    progress_cb=_p,
                )
                if signed.get("ok"):
                    _p(f"Tour ready — {plat['name']} video saved.")
                    return signed
                notes.extend(list(signed.get("notes") or []))
                notes.append(f"signed_tour_failed:{(signed.get('message') or '')[:160]}")
                _p(f"Continuous short — recording {plat['name']} page-by-page live…")
        except Exception as exc:
            notes.append(f"signed_tour_error: {exc}")
            _p(f"Recording {plat['name']} page-by-page live…")
    else:
        notes.append("mode=live_page_clips_primary")
        _p(f"Recording live {plat['name']} pages (screen tour)…")

    if not plat.get("steps"):
        return {"ok": False, "status": "error", "message": f"No tour steps for {plat['id']}", "notes": notes}

    steps, plan_notes = _plan_tour_steps(topic, plat)
    notes.extend(plan_notes)
    if not steps:
        return {"ok": False, "status": "error", "message": f"No tour steps for {plat['id']}", "notes": notes}

    deep = _wants_deep_tour(topic)
    quick = _wants_quick_tour(topic)
    from jarvis.mira.demo_actions import wants_feature_demos

    deep_demo = wants_feature_demos(topic) and not quick
    n = len(steps)
    notes.append(f"platform={plat['id']}")
    notes.append(f"steps={n}")
    notes.append(f"deep={deep}")
    notes.append(f"feature_demos={deep_demo}")
    notes.append("fallback=public_clip_tour")
    if deep_demo:
        _p("Full demo mode — Mira will USE features (chat, agents, search), not only scroll…")
    _p(f"Exploring all {n} unique {plat['name']} pages live…")

    vertical = aspect in ("9:16", "vertical", "shorts", "reel")
    width, height = (720, 1280) if vertical else (1280, 720)
    out_w, out_h = (1080, 1920) if vertical else (1920, 1080)

    root = Path(out_root) if out_root else Path(__file__).resolve().parents[2] / "data" / "mira"
    clips_dir = root / "clips" / "platforms"
    audio_dir = root / "audio"
    videos_dir = root / "videos"
    clips_dir.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)
    videos_dir.mkdir(parents=True, exist_ok=True)

    recorded = _record_tour_clips(
        steps,
        clips_dir,
        width=width,
        height=height,
        index_base=0,
        platform_id=plat["id"],
        deep_demo=deep_demo,
        progress_cb=_p,
    )
    raw_clips: list[tuple[Path, str, str]] = []
    for i, (clip, trim, step) in enumerate(recorded):
        notes.append(f"recording:{step.get('url')}")
        mp4 = clip if clip.suffix.lower() == ".mp4" else clips_dir / f"{clip.stem}.mp4"
        try:
            if clip.suffix.lower() != ".mp4":
                _webm_to_mp4(clip, mp4, trim_start_sec=trim)
                notes.append(f"trim_start_{i}={trim:.1f}s")
                try:
                    clip.unlink(missing_ok=True)
                except Exception:
                    pass
            else:
                notes.append(f"clip_already_mp4:{i}")
            sz = mp4.stat().st_size
            if sz < 20_000:
                notes.append(f"step_too_short:{i}")
                continue
            ui_ok = _verify_mp4_has_ui(mp4, at_sec=0.6)
            if not ui_ok:
                if sz >= 120_000:
                    notes.append(f"step_kept_dark_ui:{i}")
                else:
                    notes.append(f"step_blank_frame:{i}")
                    continue
            line = str(step.get("line") or f"This is {plat['name']}.").strip()
            raw_clips.append((mp4, line, str(step.get("url") or "")))
        except Exception as exc:
            notes.append(f"convert_failed:{exc}")
            continue

    if recorded and len(raw_clips) < max(1, len(recorded) // 2):
        notes.append(f"clip_drop_warning:kept={len(raw_clips)}/{len(recorded)}")

    if len(raw_clips) < 1:
        return {
            "ok": False,
            "status": "error",
            "message": (
                f"Could not screen-record {plat['name']} "
                f"(got {len(raw_clips)} clips from {len(recorded)} recorded). "
                "Check network / Playwright Chromium."
            ),
            "notes": notes,
            "platform": plat["id"],
        }

    _p(f"Encoding {len(raw_clips)} live {plat['name']} scenes into your video…")

    mode = (audio_mode or "voice").strip().lower()
    need_vo = mode in ("voice", "both")
    beats: list[dict[str, Any]] = []
    for i, (path, line, url) in enumerate(raw_clips):
        entry: dict[str, Any] = {
            "tag": f"p{i}",
            "kind": "platform",
            "source": "platform_record",
            "visual": str(path),
            "audio": "",
            "line": line if need_vo else "",
            "heading": plat["name"].upper() if i == 0 else "",
            "query": plat["id"],
            "platform_url": url,
        }
        if need_vo:
            try:
                from jarvis.mira.pipeline import generate_voiceover, _stem

                vo_path = audio_dir / f"{_stem(f'{plat['id']}_p{i}', 'vo')}.mp3"
                generate_voiceover(line, vo_path, voice=voice)
                entry["audio"] = str(vo_path)
            except Exception as exc:
                notes.append(f"vo_skip:{exc}")
        beats.append(entry)

    from jarvis.mira.fast_encode import build_fast_synced_beats

    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_path = videos_dir / f"vid_{plat['id']}_tour_{stamp}_{uuid.uuid4().hex[:6]}.mp4"
    try:
        video_path = build_fast_synced_beats(
            beats,
            out_path,
            fps=30,
            bitrate="12000k",
            out_size=(out_w, out_h),
            audio_mode=mode if mode in ("voice", "ambient", "both", "mute") else "voice",
            fit_mode="cover",
            preset="veryfast",
            smooth=not quick,
        )
    except Exception as exc:
        return {
            "ok": False,
            "status": "error",
            "message": f"Platform tour encode failed: {exc}"[:240],
            "notes": notes,
            "beats": beats,
            "platform": plat["id"],
        }

    if not _verify_mp4_has_ui(Path(video_path), at_sec=0.8):
        return {
            "ok": False,
            "status": "error",
            "message": f"Tour video looked blank after encode ({Path(video_path).name})",
            "notes": notes + ["final_frame_blank"],
            "platform": plat["id"],
        }

    script = " ".join(b["line"] for b in beats if b.get("line")).strip() or topic
    return {
        "ok": True,
        "status": "ok",
        "action": "create_video",
        "topic": topic,
        "script": script,
        "video_path": str(video_path),
        "duration_sec": int(duration_sec or 45),
        "aspect": aspect,
        "audio_mode": mode,
        "provider": "mira_platform_screen_record",
        "still_source": "platform_record",
        "platform": plat["id"],
        "platform_name": plat["name"],
        "beats": beats,
        "mira_engine": True,
        "is_trained_foundation_model": False,
        "message": f"Platform tour ready: {plat['name']} ({len(beats)} scenes · {video_path.name})",
        "notes": notes,
        "learning_note": "Real site recording — rate with mira_rate to improve tours.",
    }
