"""Autonomy gates: hard-pause for pay/danger; hard-refuse for illegal requests."""

from __future__ import annotations

import re

# Payments / irreversible — ask once, allow "yes proceed"
_HARD_PAUSE_RE = re.compile(
    r"\b("
    r"pay|payment|purchase|buy|checkout|order\s+now|"
    r"transfer\s+money|wire\s+transfer|send\s+money|"
    r"delete\s+(my\s+)?account|close\s+(my\s+)?account|"
    r"drop\s+(the\s+)?database|format\s+(the\s+)?(disk|drive|c:)"
    r")\b",
    re.I,
)

_CONFIRM_GO_RE = re.compile(
    r"\b(yes\s+(do\s+it|proceed|confirm)|confirm\s+(payment|purchase|buy)|proceed\s+anyway)\b",
    re.I,
)

# Illegal / clearly harmful — refuse, no proceed
_ILLEGAL_RE = re.compile(
    r"\b("
    r"hack\s+(into|someone|their|his|her)|phishing|steal\s+(password|credentials|card)|"
    r"credit\s+card\s+fraud|make\s+a\s+bomb|build\s+a\s+bomb|synthesize\s+(fentanyl|meth)|"
    r"child\s+porn|csam|sex\s+with\s+(a\s+)?(minor|child)|"
    r"assassinate|how\s+to\s+murder|hire\s+a\s+hitman|"
    r"ddos\s+attack|ransomware|"
    r"bypass\s+(bank|paypal)\s+security|clone\s+a\s+credit\s+card"
    r")\b",
    re.I,
)

_pending_dangerous: str | None = None


def is_illegal(text: str) -> bool:
    return bool(_ILLEGAL_RE.search(text or ""))


def illegal_message() -> str:
    return (
        "I won't do that, sir — it's illegal or I don't have the right to do it. "
        "Ask me something lawful and I'll handle it."
    )


def is_hard_pause(text: str) -> bool:
    if is_illegal(text or ""):
        return False
    return bool(_HARD_PAUSE_RE.search(text or ""))


def is_danger_confirm(text: str) -> bool:
    return bool(_CONFIRM_GO_RE.search(text or ""))


def pause_message(text: str) -> str:
    global _pending_dangerous
    _pending_dangerous = (text or "").strip()
    return (
        "That looks like a payment or irreversible action, sir. "
        "Say 'yes proceed' to continue, or give a different command to cancel."
    )


def take_pending_if_confirmed(text: str) -> str | None:
    """If user confirmed, return the original dangerous command; else None."""
    global _pending_dangerous
    if not _pending_dangerous:
        return None
    if is_danger_confirm(text):
        cmd = _pending_dangerous
        _pending_dangerous = None
        return cmd
    if text and text.strip():
        _pending_dangerous = None
    return None
