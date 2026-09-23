"""Interactive platform demos for full Mira tours.

When the Owner asks for a FULL video, Mira should not only scroll pages —
it should USE features (type in chat, click agents/API/pricing, search, etc.)
so the video looks like a real product ad.

Safety rules:
- Failures never abort the tour (each action is try/except).
- Quick/teaser tours skip demos entirely.
- Prefer public UI; never invent credentials or force destructive clicks.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Callable
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

ProgressCb = Callable[[str], None] | None


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def wants_feature_demos(topic: str) -> bool:
    """Full / deep / ad-style asks get interactive demos; quick teasers do not."""
    t = _norm(topic)
    if re.search(
        r"\b(quick|short|brief|teaser|preview|snippet|30\s*sec|15\s*sec|"
        r"one\s+minute|1\s*min|highlights?\s+only)\b",
        t,
    ):
        return False
    if re.search(
        r"\b(full|entire|complete|every|all|deep|explore|walk\s*through|"
        r"whole|everything|demo|advert|ad\b|showcase|all\s+features|"
        r"every\s+feature|use\s+(?:every|all|each)|try\s+(?:every|all))\b",
        t,
    ):
        return True
    # Named platform video defaults to full = demos on
    return True


def _safe_click(page: Any, selectors: list[str], *, timeout: int = 2500) -> bool:
    for sel in selectors:
        try:
            loc = page.locator(sel)
            if loc.count() <= 0:
                continue
            target = loc.first
            if not target.is_visible(timeout=800):
                continue
            target.click(timeout=timeout)
            return True
        except Exception:
            continue
    return False


def _safe_click_text(page: Any, labels: list[str], *, timeout: int = 2500) -> bool:
    for label in labels:
        try:
            loc = page.get_by_role("button", name=re.compile(rf"^\s*{re.escape(label)}\s*$", re.I))
            if loc.count() > 0 and loc.first.is_visible(timeout=600):
                loc.first.click(timeout=timeout)
                return True
        except Exception:
            pass
        try:
            loc = page.get_by_role("link", name=re.compile(rf"{re.escape(label)}", re.I))
            if loc.count() > 0 and loc.first.is_visible(timeout=600):
                loc.first.click(timeout=timeout)
                return True
        except Exception:
            pass
        try:
            loc = page.locator(f"a:has-text('{label}'), button:has-text('{label}')")
            if loc.count() > 0 and loc.first.is_visible(timeout=600):
                loc.first.click(timeout=timeout)
                return True
        except Exception:
            pass
    return False


def _find_editable(page: Any) -> Any | None:
    """Prefer chat prompt boxes, then search, then any visible text input."""
    selectors = (
        "textarea[placeholder*='Message' i]",
        "textarea[placeholder*='Ask' i]",
        "textarea[placeholder*='prompt' i]",
        "textarea[placeholder*='Chat' i]",
        "div[contenteditable='true'][data-placeholder]",
        "div[contenteditable='true']",
        "textarea",
        "input[type='search']",
        "input[placeholder*='Search' i]",
        "input[placeholder*='Ask' i]",
        "input[type='text']",
    )
    for sel in selectors:
        try:
            loc = page.locator(sel)
            n = min(loc.count(), 6)
            for i in range(n):
                el = loc.nth(i)
                try:
                    if el.is_visible(timeout=400):
                        return el
                except Exception:
                    continue
        except Exception:
            continue
    return None


def _type_into(page: Any, text: str, *, submit: bool = False) -> bool:
    el = _find_editable(page)
    if el is None:
        return False
    try:
        el.click(timeout=2000)
        page.wait_for_timeout(120)
        try:
            el.fill("")
        except Exception:
            pass
        # Human-ish typing for the ad look
        try:
            el.type(text, delay=28)
        except Exception:
            el.fill(text)
        page.wait_for_timeout(350)
        if submit:
            try:
                page.keyboard.press("Enter")
                page.wait_for_timeout(1200)
            except Exception:
                # Try send button
                _safe_click_text(page, ["Send", "Submit", "Ask", "Go", "Search"])
                page.wait_for_timeout(800)
        return True
    except Exception as exc:
        logger.debug("type_into failed: %s", exc)
        return False


def _path_key(url: str) -> str:
    try:
        return (urlparse(url).path or "/").rstrip("/").lower() or "/"
    except Exception:
        return "/"


# --- Per-platform demo recipes (matched by URL path keywords) -----------------

def _demos_cursor(url: str) -> list[dict[str, Any]]:
    path = _path_key(url)
    if "pricing" in path:
        return [
            {"op": "note", "text": "Exploring Cursor pricing tiers"},
            {"op": "click_text", "labels": ["Pro", "Business", "Hobby", "Pricing"]},
            {"op": "scroll", "y": 900},
            {"op": "wait", "ms": 600},
        ]
    if "feature" in path:
        return [
            {"op": "note", "text": "Showing Cursor chat, edits, and agents"},
            {"op": "click_text", "labels": ["Chat", "Agent", "Agents", "Tab", "Features"]},
            {"op": "scroll", "y": 800},
            {"op": "type", "text": "Refactor this function and add tests", "submit": False},
            {"op": "wait", "ms": 700},
            {"op": "scroll", "y": 1400},
        ]
    if "changelog" in path:
        return [
            {"op": "scroll", "y": 700},
            {"op": "click_text", "labels": ["Read more", "Learn more"]},
            {"op": "wait", "ms": 500},
        ]
    # Home / default
    return [
        {"op": "note", "text": "Cursor homepage — AI code editor"},
        {"op": "click_text", "labels": ["Features", "Download", "Get started", "Try Cursor"]},
        {"op": "wait", "ms": 700},
        {"op": "type", "text": "Build a FastAPI endpoint with auth", "submit": False},
        {"op": "wait", "ms": 600},
        {"op": "scroll", "y": 1000},
    ]


def _demos_chatgpt(url: str) -> list[dict[str, Any]]:
    path = _path_key(url)
    if "pricing" in path or "overview" in path:
        return [
            {"op": "scroll", "y": 800},
            {"op": "click_text", "labels": ["Plus", "Team", "Get started", "Try ChatGPT"]},
            {"op": "wait", "ms": 600},
            {"op": "scroll", "y": 1400},
        ]
    return [
        {"op": "note", "text": "Using ChatGPT chat box"},
        {"op": "type", "text": "Explain quantum computing in one short paragraph", "submit": True},
        {"op": "wait", "ms": 2200},
        {"op": "scroll", "y": 400},
        {"op": "click_text", "labels": ["New chat", "ChatGPT", "Explore GPTs"]},
        {"op": "wait", "ms": 700},
    ]


def _demos_gemini(url: str) -> list[dict[str, Any]]:
    path = _path_key(url)
    if "docs" in path or "ai.google.dev" in (url or "").lower():
        return [
            {"op": "note", "text": "Browsing Gemini API docs"},
            {"op": "click_text", "labels": ["Get API key", "Quickstart", "Gemini API", "Docs"]},
            {"op": "type", "text": "gemini generateContent", "submit": False},
            {"op": "wait", "ms": 600},
            {"op": "scroll", "y": 1100},
        ]
    if "deepmind" in (url or "").lower():
        return [
            {"op": "scroll", "y": 900},
            {"op": "click_text", "labels": ["Models", "Research", "Try Gemini", "Learn more"]},
            {"op": "wait", "ms": 700},
            {"op": "scroll", "y": 1800},
        ]
    return [
        {"op": "note", "text": "Using Gemini chat"},
        {"op": "type", "text": "Plan a 3-day trip to Tokyo with food tips", "submit": True},
        {"op": "wait", "ms": 2200},
        {"op": "click_text", "labels": ["Try Gemini", "Chat", "New chat"]},
        {"op": "scroll", "y": 500},
    ]


def _demos_cryptorafts(url: str) -> list[dict[str, Any]]:
    path = _path_key(url)
    u = (url or "").lower()
    if "pricing" in path:
        return [
            {"op": "note", "text": "Comparing CryptoRafts plans"},
            {"op": "click_text", "labels": ["Starter", "Pro", "Business", "Enterprise", "Get started"]},
            {"op": "scroll", "y": 900},
            {"op": "wait", "ms": 600},
        ]
    if "dealflow" in path:
        return [
            {"op": "note", "text": "Browsing public dealflow"},
            {"op": "type", "text": "AI infrastructure", "submit": True},
            {"op": "wait", "ms": 1200},
            {"op": "click_text", "labels": ["View", "Open", "Details", "See more"]},
            {"op": "scroll", "y": 800},
        ]
    if "raftai" in path or "raftai" in u:
        return [
            {"op": "note", "text": "Exploring RaftAI agent workforce"},
            {"op": "click_text", "labels": ["Agent", "Agents", "Try", "Launch", "Start"]},
            {"op": "type", "text": "Research top DeFi protocols this week", "submit": False},
            {"op": "wait", "ms": 800},
            {"op": "scroll", "y": 1600},
        ]
    if "market" in path:
        return [
            {"op": "note", "text": "Atlas market intelligence"},
            {"op": "type", "text": "BTC", "submit": True},
            {"op": "wait", "ms": 1000},
            {"op": "scroll", "y": 1200},
        ]
    if "airdrop" in path:
        return [
            {"op": "scroll", "y": 700},
            {"op": "click_text", "labels": ["Connect", "Verify", "Campaign", "Wallet"]},
            {"op": "wait", "ms": 700},
        ]
    if "contact" in path or "blog" in path:
        return [
            {"op": "scroll", "y": 600},
            {"op": "type", "text": "Partnership inquiry", "submit": False},
            {"op": "wait", "ms": 500},
        ]
    # Home + general features
    return [
        {"op": "note", "text": "CryptoRafts home — using live features"},
        {"op": "click_text", "labels": ["Decline", "Accept"]},  # clear cookie if still up
        {"op": "wait", "ms": 400},
        {"op": "type", "text": "venture capital AI", "submit": True},
        {"op": "wait", "ms": 1000},
        {"op": "click_text", "labels": ["Features", "Dealflow", "Pricing", "RaftAI", "Sign up"]},
        {"op": "wait", "ms": 800},
        {"op": "scroll", "y": 1400},
    ]


def _demos_generic(url: str) -> list[dict[str, Any]]:
    path = _path_key(url)
    if "api" in path or "key" in path or "auth" in path or "docs" in path:
        return [
            {"op": "note", "text": "Opening API / docs — looking for keys and auth"},
            {"op": "click_text", "labels": ["API key", "API Keys", "Authentication", "Docs", "Quickstart", "Get started"]},
            {"op": "type", "text": "API key", "submit": False},
            {"op": "wait", "ms": 700},
            {"op": "scroll", "y": 1100},
        ]
    if "pricing" in path:
        return [
            {"op": "click_text", "labels": ["Pricing", "Plans", "Pro", "Free", "Get started"]},
            {"op": "scroll", "y": 900},
            {"op": "wait", "ms": 500},
        ]
    return [
        {"op": "click_text", "labels": ["Features", "Product", "Docs", "API", "Pricing", "Get started", "Try"]},
        {"op": "wait", "ms": 500},
        {"op": "type", "text": "Show me how this works", "submit": False},
        {"op": "wait", "ms": 500},
        {"op": "scroll", "y": 900},
    ]


def _demos_elevenlabs(url: str) -> list[dict[str, Any]]:
    path = _path_key(url)
    u = (url or "").lower()
    if "auth" in path or "api" in path or "docs" in u:
        return [
            {"op": "note", "text": "ElevenLabs API docs — finding API key / auth"},
            {"op": "click_text", "labels": ["API key", "Authentication", "Quickstart", "Get started", "Docs"]},
            {"op": "type", "text": "API key", "submit": False},
            {"op": "wait", "ms": 700},
            {"op": "scroll", "y": 1100},
        ]
    if "app" in path:
        return [
            {"op": "note", "text": "ElevenLabs app — voices and settings"},
            {"op": "click_text", "labels": ["Speech", "Voices", "Settings", "API", "Profile"]},
            {"op": "type", "text": "Hello from Jarvis Mira voice demo", "submit": False},
            {"op": "wait", "ms": 800},
            {"op": "scroll", "y": 600},
        ]
    return [
        {"op": "note", "text": "ElevenLabs home"},
        {"op": "click_text", "labels": ["Sign up", "Get started", "Developers", "API", "Docs", "Pricing"]},
        {"op": "wait", "ms": 700},
        {"op": "type", "text": "text to speech", "submit": False},
        {"op": "scroll", "y": 1200},
    ]


_DEMO_BUILDERS = {
    "cursor": _demos_cursor,
    "chatgpt": _demos_chatgpt,
    "gemini": _demos_gemini,
    "cryptorafts": _demos_cryptorafts,
    "elevenlabs": _demos_elevenlabs,
    "fishaudio": _demos_generic,
    "groq": _demos_generic,
    "stripe": _demos_generic,
    "notion": _demos_generic,
    "openai": _demos_generic,
}


def demos_for_step(platform_id: str, url: str) -> list[dict[str, Any]]:
    builder = _DEMO_BUILDERS.get(str(platform_id or "").lower())
    if builder:
        return list(builder(url))
    return list(_demos_generic(url))


def run_demo_actions(
    page: Any,
    platform_id: str,
    url: str,
    *,
    progress_cb: ProgressCb = None,
    on_frame: Callable[[], None] | None = None,
    max_sec: float = 18.0,
) -> list[str]:
    """Run interactive demos on the live page. Never raises — returns action notes."""
    notes: list[str] = []
    if page is None:
        return notes
    actions = demos_for_step(platform_id, url)
    if not actions:
        return notes
    t0 = time.time()

    def _prog(msg: str) -> None:
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    def _frame() -> None:
        if on_frame:
            try:
                on_frame()
            except Exception:
                pass

    _prog(f"Demonstrating {platform_id} features…")
    for action in actions:
        if (time.time() - t0) >= max_sec:
            notes.append("demo_budget_done")
            break
        op = str(action.get("op") or "").lower()
        try:
            if op == "note":
                notes.append(f"demo:{action.get('text')}")
                _prog(str(action.get("text") or "Demoing feature…")[:90])
            elif op == "wait":
                page.wait_for_timeout(int(action.get("ms") or 500))
                _frame()
            elif op == "scroll":
                y = int(action.get("y") or 800)
                page.evaluate(f"window.scrollTo({{top: {y}, behavior: 'smooth'}})")
                page.wait_for_timeout(450)
                _frame()
                notes.append(f"demo_scroll:{y}")
            elif op == "click_text":
                labels = [str(x) for x in (action.get("labels") or []) if str(x).strip()]
                if _safe_click_text(page, labels):
                    notes.append(f"demo_click:{labels[0]}")
                    page.wait_for_timeout(500)
                    _frame()
                else:
                    notes.append(f"demo_click_miss:{labels[:2]}")
            elif op == "click_css":
                sels = [str(x) for x in (action.get("selectors") or []) if str(x).strip()]
                if _safe_click(page, sels):
                    notes.append("demo_click_css")
                    page.wait_for_timeout(450)
                    _frame()
            elif op == "type":
                text = str(action.get("text") or "Hello from Jarvis Mira")[:120]
                submit = bool(action.get("submit"))
                if _type_into(page, text, submit=submit):
                    notes.append("demo_type" + ("_submit" if submit else ""))
                    _frame()
                    if submit:
                        page.wait_for_timeout(900)
                        _frame()
                else:
                    notes.append("demo_type_miss")
            else:
                notes.append(f"demo_skip_op:{op}")
        except Exception as exc:
            notes.append(f"demo_err:{op}:{exc}"[:80])
            logger.debug("demo action %s failed: %s", op, exc)
            continue
    return notes
