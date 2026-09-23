"""Google Calendar via Calendar API v3 + OAuth (desktop).

Setup once:
  1. Google Cloud Console → enable Calendar API
  2. Create OAuth client (Desktop) → download JSON to data/google_credentials.json
     OR set GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET in .env
  3. Say: connect google calendar  (browser consent once)
Token saved to data/google_calendar_token.json
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
CREDENTIALS_PATH = ROOT / "data" / "google_credentials.json"
TOKEN_PATH = ROOT / "data" / "google_calendar_token.json"
PENDING_PATH = ROOT / "data" / "calendar_pending.json"

SCOPES = ["https://www.googleapis.com/auth/calendar"]
# Prefer local Windows timezone; fall back to US Pacific (user is UTC-7)
try:
    LOCAL_TZ = ZoneInfo("America/Los_Angeles")
except Exception:
    LOCAL_TZ = datetime.now().astimezone().tzinfo


def _reload_env() -> None:
    load_dotenv(ROOT / ".env", override=True)


def _client_config() -> dict | None:
    """Return installed-app OAuth client config, or None."""
    _reload_env()
    if CREDENTIALS_PATH.exists():
        try:
            data = json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))
            if "installed" in data or "web" in data:
                return data
        except (json.JSONDecodeError, OSError):
            pass
    cid = (os.getenv("GOOGLE_CLIENT_ID") or "").strip()
    csec = (os.getenv("GOOGLE_CLIENT_SECRET") or "").strip()
    if cid and csec:
        return {
            "installed": {
                "client_id": cid,
                "client_secret": csec,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        }
    return None


def config_help() -> str:
    return (
        "Google Calendar is not connected yet, sir.\n"
        "1) In Google Cloud Console: enable Calendar API, create OAuth Desktop credentials.\n"
        "2) Save the JSON as data/google_credentials.json "
        "(or set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env).\n"
        "3) Say: connect google calendar\n"
        "A browser will open once to approve access."
    )


def credentials_ready() -> bool:
    return _client_config() is not None


def connected() -> bool:
    return TOKEN_PATH.exists() and credentials_ready()


def _build_flow():
    from google_auth_oauthlib.flow import InstalledAppFlow

    cfg = _client_config()
    if not cfg:
        return None
    return InstalledAppFlow.from_client_config(cfg, SCOPES)


def _load_creds():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if not TOKEN_PATH.exists():
        return None
    try:
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    except Exception:
        return None
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        except Exception:
            return None
    if creds and creds.valid:
        return creds
    return None


def connect() -> str:
    """Run browser OAuth once; save refresh token."""
    if not credentials_ready():
        return config_help()
    existing = _load_creds()
    if existing:
        return "Google Calendar already connected, sir. Try 'what's on my calendar today'."
    try:
        flow = _build_flow()
        if not flow:
            return config_help()
        creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
        TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        return "Google Calendar connected, sir. Try 'what's on my calendar today'."
    except Exception as exc:
        return f"Calendar connect failed, sir: {exc}"


def _service():
    from googleapiclient.discovery import build

    creds = _load_creds()
    if not creds:
        return None
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _fmt_when(start: dict, end: dict | None = None) -> str:
    if "date" in start:
        return start["date"]  # all-day
    raw = start.get("dateTime") or ""
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(LOCAL_TZ)
        stamp = dt.strftime("%a %b %d %I:%M %p").lstrip("0")
        if end and end.get("dateTime"):
            et = datetime.fromisoformat(end["dateTime"].replace("Z", "+00:00")).astimezone(LOCAL_TZ)
            stamp += "–" + et.strftime("%I:%M %p").lstrip("0")
        return stamp
    except Exception:
        return raw[:16]


def list_events(days: int = 1, limit: int = 10) -> str:
    if not credentials_ready():
        return config_help()
    if not _load_creds():
        return "Calendar not authorized yet, sir. Say: connect google calendar"
    svc = _service()
    if not svc:
        return "Calendar not authorized yet, sir. Say: connect google calendar"

    days = max(1, min(int(days), 30))
    limit = max(1, min(int(limit), 20))
    now = datetime.now(LOCAL_TZ)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=days)

    try:
        result = (
            svc.events()
            .list(
                calendarId="primary",
                timeMin=start.isoformat(),
                timeMax=end.isoformat(),
                maxResults=limit,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        items = result.get("items") or []
        if not items:
            label = "today" if days == 1 else f"the next {days} days"
            return f"No events {label}, sir."
        label = "today" if days == 1 else f"next {days} days"
        lines = [f"{len(items)} event(s) {label}:"]
        for i, ev in enumerate(items, 1):
            title = ev.get("summary") or "(no title)"
            when = _fmt_when(ev.get("start") or {}, ev.get("end"))
            lines.append(f"{i}. [{when}] {title}")
        return "\n".join(lines)
    except Exception as exc:
        err = str(exc).lower()
        if "invalid_grant" in err or "expired" in err:
            try:
                TOKEN_PATH.unlink(missing_ok=True)
            except OSError:
                pass
            return "Calendar token expired, sir. Say: connect google calendar"
        return f"Calendar error, sir: {exc}"


def _parse_duration_minutes(text: str) -> int:
    m = re.search(r"\bfor\s+(\d+)\s*(hours?|hrs?|h|minutes?|mins?|m)\b", text, re.I)
    if not m:
        return 60
    n = int(m.group(1))
    unit = m.group(2).lower()
    if unit.startswith("h"):
        return n * 60
    return n


def _parse_when(text: str) -> tuple[datetime, datetime] | None:
    """Parse relative date/time → (start, end) in LOCAL_TZ."""
    lower = text.lower()
    now = datetime.now(LOCAL_TZ)
    base = now.replace(second=0, microsecond=0)

    # Date part
    if re.search(r"\btoday\b", lower):
        day = base
    elif re.search(r"\btomorrow\b", lower):
        day = base + timedelta(days=1)
    else:
        # weekday name
        weekdays = {
            "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
            "friday": 4, "saturday": 5, "sunday": 6,
        }
        day = None
        for name, idx in weekdays.items():
            if re.search(rf"\b{name}\b", lower):
                delta = (idx - base.weekday()) % 7
                if delta == 0 and not re.search(r"\bthis\b", lower):
                    delta = 7  # next occurrence if not "this"
                if re.search(rf"\bnext\s+{name}\b", lower):
                    delta = ((idx - base.weekday()) % 7) or 7
                day = base + timedelta(days=delta)
                break
        if day is None:
            # explicit date like Sep 10 / 9/10 / 2026-09-10
            m = re.search(
                r"\b(?:on\s+)?(\d{4})-(\d{1,2})-(\d{1,2})\b",
                lower,
            )
            if m:
                day = base.replace(
                    year=int(m.group(1)), month=int(m.group(2)), day=int(m.group(3))
                )
            else:
                m = re.search(
                    r"\b(?:on\s+)?(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{1,2})\b",
                    lower,
                )
                if m:
                    months = {
                        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
                    }
                    month = months[m.group(1)[:3]]
                    d = int(m.group(2))
                    year = base.year
                    day = base.replace(month=month, day=d, year=year)
                    if day.date() < base.date():
                        day = day.replace(year=year + 1)
                else:
                    m = re.search(r"\b(?:on\s+)?(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", lower)
                    if m:
                        month, d = int(m.group(1)), int(m.group(2))
                        year = int(m.group(3)) if m.group(3) else base.year
                        if year < 100:
                            year += 2000
                        day = base.replace(month=month, day=d, year=year)
                    else:
                        day = base  # default today if time present

    # Time part — require "at N" or am/pm (avoid matching "for 30 minutes")
    tm = re.search(
        r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b"
        r"|\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b",
        lower,
    )
    if not tm and not re.search(r"\ball[\s-]?day\b", lower):
        if not re.search(
            r"\b(today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
            lower,
        ):
            return None
        return None

    if re.search(r"\ball[\s-]?day\b", lower):
        start = day.replace(hour=0, minute=0)
        end = start + timedelta(days=1)
        return start, end

    if tm.lastindex and tm.group(1):
        hour = int(tm.group(1))
        minute = int(tm.group(2) or 0)
        ampm = (tm.group(3) or "").lower()
    else:
        hour = int(tm.group(4))
        minute = int(tm.group(5) or 0)
        ampm = (tm.group(6) or "").lower()
    if ampm == "pm" and hour < 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    elif not ampm and hour < 8:
        # bare "3" → 3pm heuristic for afternoon
        hour += 12
    start = day.replace(hour=hour, minute=minute)
    mins = _parse_duration_minutes(lower)
    end = start + timedelta(minutes=mins)
    return start, end


def _extract_title(text: str) -> str:
    lower = text.lower()
    # "called X" / "titled X" / "subject X" / "about X"
    for pat in (
        r"\b(?:called|titled|title|subject|named|about)\s+(.+?)(?:\s+(?:tomorrow|today|on|at|for|from)\b|$)",
        r"\bschedule\s+(.+?)(?:\s+(?:tomorrow|today|on|at|for|from)\b)",
        r"\b(?:create|add|make)\s+(?:an?\s+)?(?:event|meeting|appointment)\s+(.+?)(?:\s+(?:tomorrow|today|on|at|for|from)\b)",
    ):
        m = re.search(pat, lower, re.I)
        if m:
            title = m.group(1).strip(" .,\"'")
            if title and title not in ("event", "meeting", "appointment"):
                return title.title() if title.islower() else title
    # Fallback: strip command words
    cleaned = re.sub(
        r"\b(schedule|create|add|make|an?|event|meeting|appointment|on my calendar|calendar|"
        r"tomorrow|today|monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
        r"at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?|for\s+\d+\s*(?:hours?|hrs?|h|minutes?|mins?|m)|"
        r"all[\s-]?day|next)\b",
        " ",
        lower,
        flags=re.I,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,\"'")
    return cleaned.title() if cleaned else "Untitled event"


def draft_event(title: str, start: datetime, end: datetime, all_day: bool = False) -> str:
    """Create the event immediately (autonomy — no second confirm)."""
    if not credentials_ready():
        return config_help()
    if not _load_creds():
        return "Calendar not authorized yet, sir. Say: connect google calendar"
    PENDING_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "title": title,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "all_day": all_day,
    }
    PENDING_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return confirm_create()


def parse_and_draft(text: str) -> str | None:
    """If text looks like schedule/create event, create it. Else None."""
    lower = text.lower()
    if not re.search(
        r"\b(schedule|create|add|make)\b.{0,40}\b(event|meeting|appointment|call)\b"
        r"|\bschedule\b.{0,60}\b(at|tomorrow|today|on)\b"
        r"|\b(add|put)\b.{0,30}\b(on\s+)?(my\s+)?calendar\b",
        lower,
    ):
        return None
    when = _parse_when(text)
    if not when:
        return (
            "To schedule, say something like: "
            "schedule meeting tomorrow at 3pm called Dentist"
        )
    start, end = when
    all_day = bool(re.search(r"\ball[\s-]?day\b", lower))
    title = _extract_title(text)
    return draft_event(title, start, end, all_day=all_day)


def confirm_create() -> str:
    if not PENDING_PATH.exists():
        return "No event draft waiting, sir."
    if not _load_creds():
        return "Calendar not authorized yet, sir. Say: connect google calendar"
    try:
        data = json.loads(PENDING_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return "Corrupt event draft, sir. Please schedule again."
    svc = _service()
    if not svc:
        return "Calendar not authorized yet, sir. Say: connect google calendar"

    title = data["title"]
    start = datetime.fromisoformat(data["start"])
    end = datetime.fromisoformat(data["end"])
    all_day = bool(data.get("all_day"))

    body: dict
    if all_day:
        body = {
            "summary": title,
            "start": {"date": start.date().isoformat()},
            "end": {"date": end.date().isoformat()},
        }
    else:
        body = {
            "summary": title,
            "start": {"dateTime": start.isoformat(), "timeZone": str(LOCAL_TZ)},
            "end": {"dateTime": end.isoformat(), "timeZone": str(LOCAL_TZ)},
        }
    try:
        created = svc.events().insert(calendarId="primary", body=body).execute()
        try:
            PENDING_PATH.unlink(missing_ok=True)
        except OSError:
            pass
        link = created.get("htmlLink") or ""
        msg = f"Event created, sir: {title}."
        if link:
            msg += f"\n{link}"
        return msg
    except Exception as exc:
        return f"Could not create event, sir: {exc}"


def cancel_pending() -> str:
    if not PENDING_PATH.exists():
        return "No event draft to cancel, sir."
    try:
        PENDING_PATH.unlink(missing_ok=True)
    except OSError:
        pass
    return "Event draft discarded, sir."
