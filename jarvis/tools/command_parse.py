"""Shared voice-command parsing — extract intent from messy speech."""

from __future__ import annotations

import re

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", re.I)
URL_RE = re.compile(
    r"https?://[^\s<>\"']+|"
    r"(?:docs\.google\.com|drive\.google\.com|sheets\.google)[^\s]+",
    re.I,
)
WINDOWS_PATH_RE = re.compile(r"[A-Za-z]:\\(?:[^\\/:*?\"<>|\r\n]+\\)*[^\\/:*?\"<>|\r\n]*")

FILLER_WORDS = (
    "hey jarvis", "hi jarvis", "hello jarvis", "jarvis",
    "please", "can you", "could you", "would you",
)

# Voice often hears "a" / "the" before song names
_SEARCH_PREFIX = r"(?:search|play|find|look\s+up)\s+(?:for\s+)?(?:a\s+|the\s+)?"


def normalize(text: str) -> str:
    t = text.lower().strip()
    for f in FILLER_WORDS:
        t = t.replace(f, " ")
    return re.sub(r"\s+", " ", t).strip()


def extract_email(text: str) -> str | None:
    m = EMAIL_RE.search(text)
    return m.group(0) if m else None


def extract_urls(text: str) -> list[str]:
    urls = URL_RE.findall(text)
    cleaned: list[str] = []
    for u in urls:
        u = u.rstrip(".,;)")
        if not u.startswith("http"):
            u = "https://" + u
        cleaned.append(u)
    return cleaned


def extract_windows_paths(text: str) -> list[str]:
    return [m.group(0).strip() for m in WINDOWS_PATH_RE.finditer(text)]


def is_youtube_command(text: str) -> bool:
    return "youtube" in normalize(text)


def is_unified_youtube_command(text: str) -> bool:
    """Don't split — handle open+search as one YouTube command."""
    lower = normalize(text)
    if "youtube" not in lower:
        return False
    return any(w in lower for w in ("search", "play", "find", "song", "music", "video"))


def extract_youtube_query(text: str) -> tuple[bool, str]:
    """Return (is_youtube_command, search_query). Empty = open YouTube home."""
    lower = normalize(text)
    if "youtube" not in lower:
        return False, ""

    # Upload / connect / Mira post — never treat as YouTube search/open
    if re.search(
        r"\b(upload|post|publish|share)\b.{0,40}\byoutube\b|"
        r"\byoutube\b.{0,30}\b(upload|post|publish)\b|"
        r"\b(post|upload)\s+(?:this|it|last|that|the)\s+(?:video|clip|short|reel)\b|"
        r"\b(connect|link|authorize|login)\b.{0,20}\byoutube\b|"
        r"\byoutube\s+(?:connect|status|auth)\b",
        lower,
    ):
        return False, ""

    patterns = [
        rf"(?:open\s+)?youtube\s+(?:and\s+)?(?:search|play|find)\s+(?:for\s+)?(?:a\s+|the\s+)?(.+)",
        rf"(?:open\s+)?youtube\s+and\s+(?:search\s+(?:for\s+)?)?(?:a\s+|the\s+)?(.+)",
        rf"{_SEARCH_PREFIX}(.+?)\s+on\s+youtube",
        rf"{_SEARCH_PREFIX}(.+?)\s+in\s+youtube",
        r"search\s+youtube\s+(?:for\s+)?(?:a\s+|the\s+)?(.+)",
        r"play\s+(?:a\s+|the\s+)?(.+?)\s+on\s+youtube",
        r"find\s+(?:a\s+|the\s+)?(.+?)\s+on\s+youtube",
        r"youtube\s+search\s+(?:for\s+)?(?:a\s+|the\s+)?(.+)",
        r"on\s+youtube\s+(?:search\s+)?(?:for\s+)?(?:a\s+|the\s+)?(.+)",
        r"in\s+youtube\s+(?:search\s+)?(?:for\s+)?(?:a\s+|the\s+)?(.+)",
    ]
    for pat in patterns:
        m = re.search(pat, lower)
        if m:
            q = _clean_yt_query(m.group(1))
            if q and q not in ("youtube", "open", "search", "play", "and", "a", "the"):
                return True, q

    if re.match(r"^(?:open\s+)?youtube\s*$", lower) or lower in ("youtube", "open youtube"):
        return True, ""

    # "search for X" while youtube mentioned anywhere
    m = re.search(rf"{_SEARCH_PREFIX}(.+)$", lower)
    if m and "youtube" in lower:
        q = _clean_yt_query(m.group(1))
        if q:
            return True, q

    return True, ""


def _clean_yt_query(q: str) -> str:
    q = q.strip().rstrip(".,!?")
    q = re.sub(r"^(?:and\s+)?(?:search|play|find|look\s+up)\s+(?:for\s+)?(?:a\s+|the\s+)?", "", q)
    q = re.sub(r"\s+on\s+youtube$", "", q)
    q = re.sub(r"\s+in\s+youtube$", "", q)
    q = re.sub(r"\s+youtube$", "", q)
    return q.strip()


def extract_search_only_query(text: str) -> str | None:
    """'search for drake' / 'play shape of you' with no site named."""
    lower = normalize(text)
    m = re.match(rf"^{_SEARCH_PREFIX}(.+)$", lower)
    if m:
        q = _clean_yt_query(m.group(1))
        return q if q else None
    return None


def is_sheet_context_command(text: str) -> bool:
    lower = normalize(text)
    markers = (
        "in the sheet", "on the sheet", "in my sheet", "on my sheet",
        "the spreadsheet", "google sheet", "google sheets", "sheet tab",
        "in the tab", "on the tab", "this sheet", "in sheet",
    )
    if any(m in lower for m in markers):
        return True
    if "sheet" in lower and any(w in lower for w in ("go to", "go on", "open", "show", "click", "navigate")):
        return True
    # Known API-sheet tab names spoken without saying "sheet"
    if re.search(r"\b(?:veridiq|veriq|veridq|phantom)\b", lower) and (
        "api" in lower or any(w in lower for w in ("open", "go to", "go on", "show", "get", "fetch"))
    ):
        return True
    return False


def extract_sheet_tab_name(text: str) -> str | None:
    """'open veridiq apis in google sheet' -> 'veridiq apis'."""
    lower = normalize(text)
    _in_sheet = r"(?:in|on)\s+(?:the\s+|my\s+)?(?:google\s+)?(?:sheet|sheets|spreadsheet)s?"
    patterns = [
        rf"go\s+(?:to|on)\s+(?:the\s+)?(.+?)\s+(?:tab\s+)?{_in_sheet}",
        rf"(?:open|show|go\s+to|navigate\s+to)\s+(?:the\s+)?(.+?)\s+(?:tab\s+)?{_in_sheet}",
        r"(?:in|on)\s+(?:the\s+|my\s+)?(?:google\s+)?sheet\s+(?:go\s+to|open|show)\s+(?:the\s+)?(.+)",
        rf"(?:click|select)\s+(?:the\s+)?(.+?)\s+(?:tab\s+)?{_in_sheet}",
        rf"go\s+(?:to|on)\s+(?:this\s+)?(.+?)\s+apis?\s+{_in_sheet}",
        # Bare tab: "open veridiq apis" / "go to phantom api tools"
        r"(?:open|show|go\s+to|go\s+on)\s+(?:the\s+)?((?:veridiq|veriq|veridq|phantom)(?:\s+api(?:\s+tools)?|\s+apis?)?)\b",
        r"\b((?:veridiq|veriq|veridq)(?:\s+apis?)?)\b",
        r"\b(phantom(?:\s+api(?:\s+tools)?|\s+apis?|\s+credentials)?)\b",
    ]
    for pat in patterns:
        m = re.search(pat, lower)
        if m:
            name = m.group(1).strip()
            name = re.sub(r"^(this|the)\s+", "", name)
            name = re.sub(r"\s+tab$", "", name).strip()
            if name and name not in ("sheet", "sheets", "tab", "google", "spreadsheet"):
                return name
    return None


def split_task_steps(text: str) -> list[str]:
    """Split compound commands — never break YouTube or sheet navigation."""
    if is_unified_youtube_command(text):
        return [text.strip()]
    if is_sheet_context_command(text):
        return [text.strip()]

    t = normalize(text)
    for sep in (" and then ", " then ", ", then "):
        if sep in t:
            parts = [p.strip() for p in t.split(sep) if p.strip()]
            if len(parts) > 1:
                return parts

    # Don't split "open youtube and search X" — handled above
    if " and " in t:
        if is_youtube_command(text) or "sheet" in t:
            return [text.strip()]
        parts = [p.strip() for p in t.split(" and ") if p.strip()]
        if 1 < len(parts) <= 5:
            return parts

    return [text.strip()]


def is_multi_step_command(text: str) -> bool:
    return len(split_task_steps(text)) > 1


def is_link_command(text: str) -> bool:
    lower = normalize(text)
    if extract_urls(text):
        return any(w in lower for w in ("open", "go to", "launch", "visit", "link", "url", "this"))
    return False


def is_sheet_command(text: str) -> bool:
    lower = normalize(text)
    return "google sheet" in lower or "spreadsheet" in lower or "sheets.google" in lower


def is_file_transfer_command(text: str) -> bool:
    lower = normalize(text)
    verbs = ("copy", "upload", "move", "transfer", "sync")
    return any(v in lower for v in verbs) and ("from" in lower or "to" in lower or extract_windows_paths(text))


def is_api_key_command(text: str) -> bool:
    from jarvis.tools.api_intent import is_api_hunt_intent
    return is_api_hunt_intent(text)
