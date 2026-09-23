"""Instant command router — no LLM delay for common tasks."""

from __future__ import annotations

import re

from jarvis.context import get_context
from jarvis.tools import system
from jarvis.tools.api_hunter import fetch_api_key
from jarvis.tools.api_intent import is_api_hunt_intent, remember_site
from jarvis.tools.api_pipeline import (
    count_apis_from_sheet,
    is_api_count_command,
    is_batch_api_command,
    paste_apis_to_sheet,
    run_batch_from_sheet,
)
from jarvis.tools.system_scanner import is_scan_command, scan_and_fix
from jarvis.tools.command_parse import (
    extract_search_only_query,
    extract_sheet_tab_name,
    extract_urls,
    extract_youtube_query,
    is_link_command,
    is_sheet_context_command,
    is_youtube_command,
    normalize,
)
from jarvis.tools.screen_share import handle_screen_share_command, is_screen_share_command
from jarvis.tools.prompt_engineer import is_prompt_engineer_intent, run_prompt_engineer
from jarvis.tools.screen_record import is_screen_record_intent, run_screen_record
from jarvis.tools.sheets import navigate_sheet_tab, open_google_sheet

SITE_MAP: dict[str, str] = {
    "eleven labs": "https://elevenlabs.io",
    "elevenlabs": "https://elevenlabs.io",
    "11 lab": "https://elevenlabs.io",
    "11 labs": "https://elevenlabs.io",
    "11labs": "https://elevenlabs.io",
    "google sheets": "https://sheets.google.com",
    "google sheet": "https://sheets.google.com",
    "sheets": "https://sheets.google.com",
    "gmail": "https://mail.google.com",
    "google calendar": "https://calendar.google.com",
    "calendar": "https://calendar.google.com",
    "github": "https://github.com",
    "chatgpt": "https://chat.openai.com",
    "openai": "https://openai.com",
    "claude": "https://claude.ai",
    "groq": "https://console.groq.com",
    "fish audio": "https://fish.audio",
    "twitter": "https://twitter.com",
    "x": "https://x.com",
    "instagram": "https://instagram.com",
    "reddit": "https://reddit.com",
    "netflix": "https://netflix.com",
    "spotify": "https://open.spotify.com",
    "whatsapp": "https://web.whatsapp.com",
    "discord": "https://discord.com/app",
    "cursor": "https://cursor.com",
}

# Wake-only: never send to LLM (allow trailing filler like "hey jarvis, hey")
_WAKE_ONLY_RE = re.compile(
    r"^(?:(?:hey|hi|hello|okay|ok)\s+)?"
    r"(?:jarvis|service|gervis|jar\s*vis)"
    r"(?:\s*(?:are you there|you there|you up|buddy))?"
    r"(?:[\s,!.?]*(?:hey|hi|hello|there|buddy)?)*"
    r"[\s,!.?]*$",
    re.I,
)

_HUMAN_VIEW_PHRASES = (
    "human view", "human interface", "face view", "jarvis face",
    "show your face", "show me your face", "open your face", "open the face",
)


def is_wake_only(text: str) -> bool:
    t = text.lower().strip()
    t = re.sub(r"\s+", " ", t)
    return bool(_WAKE_ONLY_RE.match(t))


def is_human_view_command(text: str) -> bool:
    lower = normalize(text)
    return any(p in lower for p in _HUMAN_VIEW_PHRASES)


def try_fast_command(text: str) -> str | None:
    """Return response if handled instantly, else None."""
    raw = text.strip()
    ctx = get_context()

    # ── Wake word (before normalize strips "hey jarvis") ──
    if is_wake_only(raw):
        return "Yes sir, how may I help you?"

    # ── Autonomy: illegal refuse; hard-pause only for pay / irreversible ──
    from jarvis import autonomy

    if autonomy.is_illegal(raw):
        return autonomy.illegal_message()

    confirmed = autonomy.take_pending_if_confirmed(raw)
    if confirmed:
        raw = confirmed
    elif autonomy.is_hard_pause(raw):
        return autonomy.pause_message(raw)

    # ── Prompt engineer → Cursor + email ──
    if is_prompt_engineer_intent(raw):
        return run_prompt_engineer(raw)

    # ── Screen record (ffmpeg desktop capture) ──
    if is_screen_record_intent(raw):
        return run_screen_record(raw)

    # ── Pasted screenshot read ──
    from jarvis.tools.screenshot_read import is_read_screenshot_intent, read_last_or_message

    if is_read_screenshot_intent(raw):
        return read_last_or_message(raw)

    lower = normalize(raw)

    # ── Identity switch (use my email / use jarvis email) ──
    from jarvis import identity as _identity

    if re.search(
        r"\b(use|from|with|switch)\b.{0,20}\b(my|your|jarvis)\b.{0,15}\b(email|gmail|account|mail)\b"
        r"|\bswitch\s+(?:back\s+)?to\s+jarvis\b",
        lower,
    ):
        switched = _identity.maybe_switch_from_text(raw)
        if switched and not re.search(
            r"\b(check|read|show|list|unread|inbox|subject|body|schedule|calendar)\b",
            lower,
        ):
            if "@" not in raw and not re.search(r"\b(email|mail)\s+\S+@", lower):
                return switched

    # ── Gmail (Phase 2) — before hunt / open-site ──
    from jarvis.tools import gmail_tool as _gmail

    if (
        re.search(r"\b(email|mail|inbox|gmail|unread)\b", lower)
        or _gmail.composing()
        or _identity.awaiting_mail_choice()
        or _identity.awaiting_creds()
        or _identity.pending_send()
        or re.search(r"\b(app\s*password|yours|mine)\b", lower)
        or re.search(r"\b(use|from|with)\s+my\s+(email|gmail|account)\b", lower)
    ):
        try:
            import importlib.util
            from pathlib import Path

            # __file__ is jarvis/fast_router.py → parents[1] is project root
            plugin_path = Path(__file__).resolve().parents[1] / "plugins" / "gmail.py"
            spec = importlib.util.spec_from_file_location("plugins.gmail_fast", plugin_path)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                gmail_resp = mod.handle(raw)
                if gmail_resp:
                    return gmail_resp
        except Exception:
            pass

    # ── Calendar (Phase 2) — before open-site ──
    if re.search(
        r"\b(calendar|schedule|meeting|appointment|events?)\b"
        r"|\bwhat.?s?\s+on\s+my\b"
        r"|\bcreate the event\b|\bcancel event\b",
        lower,
    ):
        try:
            import importlib.util
            from pathlib import Path

            plugin_path = Path(__file__).resolve().parents[1] / "plugins" / "calendar.py"
            spec = importlib.util.spec_from_file_location("plugins.calendar_fast", plugin_path)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                cal_resp = mod.handle(raw)
                if cal_resp:
                    return cal_resp
        except Exception:
            pass

    # Remember saved links/folders before hunt (sheet URL must never hunt)
    if "remember" in lower:
        from jarvis.tools.task_executor import try_task_command
        remembered = try_task_command(raw)
        if remembered:
            return remembered

    # ── Batch / scoped sheet API pipeline BEFORE single-key hunt ──
    if is_batch_api_command(raw):
        if "paste" in lower or "put" in lower:
            # Still run full get+paste when command also says get/fetch
            if re.search(r"\b(get|fetch|grab|fill)\b", lower):
                return run_batch_from_sheet(raw)
            return paste_apis_to_sheet(raw)
        return run_batch_from_sheet(raw)

    # ── API key hunter — NEVER fall through to Groq brain ──
    if is_api_hunt_intent(raw):
        return fetch_api_key(raw)

    # ── Sheet API count / remaining / missing — NEVER LLM ──
    if is_api_count_command(raw):
        return count_apis_from_sheet(raw)

    # ── Human View / Face — NEVER LLM ──
    if is_human_view_command(raw):
        system.open_in_chrome("http://127.0.0.1:8765/face")
        return "Opening the human interface, sir."

    # ── Screen share (user watch-me / Jarvis show-me) — NEVER LLM ──
    if is_screen_share_command(raw):
        result = handle_screen_share_command(raw)
        if result:
            return result

    # ── Sheet tab navigation (NEVER Google search / NEVER brain) ──
    if is_sheet_context_command(raw):
        tab = extract_sheet_tab_name(raw)
        if tab:
            return navigate_sheet_tab(tab)
        if "open" in lower or "go" in lower:
            urls = extract_urls(raw)
            return open_google_sheet(urls[0] if urls else None)

    # Bare veridiq / veriq tab without "sheet" wording (belt-and-suspenders)
    veridiq = re.search(
        r"(?:open|show|go\s+to|go\s+on)\s+(?:the\s+)?((?:veridiq|veriq|veridq)(?:\s+apis?)?)\b",
        lower,
    )
    if veridiq:
        return navigate_sheet_tab(veridiq.group(1).strip())

    # ── Direct URL ──
    urls = extract_urls(raw)
    if urls and (is_link_command(raw) or raw.strip().startswith("http")):
        return system.open_in_chrome(urls[0])

    # ── System self-scan / repair ──
    if is_scan_command(raw):
        return scan_and_fix(raw)

    # Mira AI generate beats YouTube search ("make a video about cats")
    from jarvis.tools.mira_tool import (
        is_mira_followup_intent,
        is_mira_generate_intent,
        try_mira_command,
    )

    if is_mira_generate_intent(raw) or is_mira_followup_intent(raw):
        mira = try_mira_command(raw, background=True)
        if mira:
            return mira

    # Explicit YouTube upload/connect before any open/search
    try:
        from jarvis.mira.youtube_upload import parse_upload_command

        yt = parse_upload_command(raw)
        if yt:
            mira = try_mira_command(raw, background=True)
            if mira:
                return mira
    except Exception:
        pass

    # ── YouTube (always before generic search/open) ──
    is_yt, yt_query = extract_youtube_query(raw)
    if is_yt:
        return system.open_youtube_in_chrome(yt_query)

    # ── Context: user was on YouTube, says "search for song" ──
    if ctx.get("mode") == "youtube":
        if is_mira_generate_intent(raw) or is_mira_followup_intent(raw):
            mira = try_mira_command(raw, background=True)
            if mira:
                return mira
        q = extract_search_only_query(raw)
        if q:
            return system.open_youtube_in_chrome(q)

    # ── Context: user was in sheet ──
    if ctx.get("mode") == "sheet":
        tab = extract_sheet_tab_name(raw)
        if tab:
            return navigate_sheet_tab(tab, ctx.get("sheet_url"))
        if any(w in lower for w in ("go to", "go on", "open", "show")) and "api" in lower:
            name = re.sub(r".*(?:go\s+(?:to|on)|open|show)\s+(?:the\s+)?", "", lower)
            name = re.sub(r"\s*(?:apis?|tab).*$", "", name).strip()
            if name:
                return navigate_sheet_tab(name, ctx.get("sheet_url"))

    # ── Time / status ──
    if lower in ("what time is it", "what's the time", "tell me the time", "time"):
        return system.get_time()
    if "system status" in lower or "how is my computer" in lower:
        return system.get_system_status()
    if "cancel shutdown" in lower:
        return system.cancel_shutdown()
    if lower in ("take a screenshot", "screenshot", "capture screen"):
        return system.take_screenshot()
    if "lock screen" in lower or lower == "lock":
        return system.lock_screen()

    # ── Volume ──
    if "volume up" in lower or "louder" in lower:
        return system.set_volume("up")
    if "volume down" in lower or "quieter" in lower:
        return system.set_volume("down")
    if "mute" in lower:
        return system.set_volume("mute")

    # ── Web search — but NOT if YouTube or sheet context ──
    search_pat = re.match(r"^(?:search|google|look up|find)\s+(?:for\s+)?(?:a\s+|the\s+)?(.+)$", lower)
    if search_pat:
        q = search_pat.group(1).strip()
        if is_youtube_command(raw) or "youtube" in q or "on youtube" in lower:
            q = q.replace("on youtube", "").replace("in youtube", "").strip()
            return system.open_youtube_in_chrome(q)
        if is_sheet_context_command(raw) or "sheet" in q or "spreadsheet" in q:
            tab = extract_sheet_tab_name(raw) or q.replace("sheet", "").strip()
            if tab:
                return navigate_sheet_tab(tab)
        return system.search_in_chrome(q)

    # ── Open in Chrome ──
    chrome_pat = re.match(
        r"^(?:open|launch|go to|start)\s+(.+?)(?:\s+in\s+chrome)?$",
        lower,
    )
    if chrome_pat:
        target = chrome_pat.group(1).strip()
        if is_youtube_command(target):
            _, q = extract_youtube_query(raw)
            return system.open_youtube_in_chrome(q)
        return _open_target_in_chrome(target)

    if lower in ("open chrome", "launch chrome", "start chrome", "chrome"):
        return system.open_in_chrome()

    close_pat = re.match(r"^close\s+(.+)$", lower)
    if close_pat:
        return system.close_application(close_pat.group(1))

    open_pat = re.match(r"^(?:open|launch|start)\s+(.+)$", lower)
    if open_pat:
        app = open_pat.group(1).strip()
        if app in system.APP_MAP:
            return system.open_application(app)

    return None


def _open_target_in_chrome(target: str) -> str:
    target = target.strip().rstrip(".")

    if is_youtube_command(target):
        _, q = extract_youtube_query(f"open {target}")
        return system.open_youtube_in_chrome(q)

    if target in SITE_MAP:
        remember_site(SITE_MAP[target], target)
        return system.open_in_chrome(SITE_MAP[target])

    for key, url in SITE_MAP.items():
        if key in target or target in key:
            remember_site(url, key)
            if key in ("google sheet", "google sheets", "sheets"):
                return open_google_sheet(url)
            return system.open_in_chrome(url)

    if "." in target or target.replace("-", "").isalnum():
        url = target if target.startswith("http") else f"https://{target.replace(' ', '')}.com"
        url = url.replace("11labs", "elevenlabs.io").replace("elevenlabs.com", "elevenlabs.io")
        if "eleven" in target and "lab" in target:
            url = "https://elevenlabs.io"
        remember_site(url, target)
        return system.open_in_chrome(url)

    if target in system.APP_MAP:
        if target == "chrome":
            return system.open_in_chrome()
        return system.open_application(target)

    # Last resort — Google search (not for sheet/youtube words)
    if "sheet" in target or "youtube" in target:
        if "youtube" in target:
            return system.open_youtube_in_chrome()
        return open_google_sheet()
    return system.search_in_chrome(target)
