"""Google Calendar plugin — list / draft / confirm for Jarvis."""

from __future__ import annotations

import re

from jarvis.tools import calendar_tool


def handle(text: str) -> str | None:
    lower = text.lower().strip()
    if not lower:
        return None

    # Auth
    if re.search(
        r"\b(connect|authorize|link|setup|set\s*up)\b.{0,20}\b(google\s+)?calendar\b"
        r"|\bcalendar\b.{0,20}\b(connect|authorize|link|setup|auth)\b",
        lower,
    ):
        return calendar_tool.connect()

    # Confirm / cancel draft
    if re.search(
        r"\b(create the event|confirm (the )?event|yes create it|add the event)\b",
        lower,
    ):
        return calendar_tool.confirm_create()
    if re.search(
        r"\b(cancel event|discard event|cancel the (event )?draft|discard draft)\b",
        lower,
    ):
        return calendar_tool.cancel_pending()

    # List
    if re.search(
        r"\b(what.?s?\s+on\s+my\s+calendar|my\s+(schedule|calendar)|calendar\s+today|"
        r"today.?s?\s+(schedule|calendar|events)|show\s+(my\s+)?(calendar|schedule|events)|"
        r"list\s+(my\s+)?(calendar|events)|any\s+(meetings?|events?)\s+today|"
        r"what\s+do\s+i\s+have\s+(today|tomorrow|this\s+week))\b",
        lower,
    ):
        days = 1
        if re.search(r"\b(week|7\s*days|next\s+7)\b", lower):
            days = 7
        elif re.search(r"\btomorrow\b", lower):
            # list tomorrow only — use time window via days=2 and filter? simpler: days=2
            days = 2
        elif m := re.search(r"\b(?:next|for)\s+(\d+)\s+days?\b", lower):
            days = int(m.group(1))
        return calendar_tool.list_events(days=days)

    # Create / schedule → create immediately
    created = calendar_tool.parse_and_draft(text)
    if created:
        return created

    if re.search(r"\bcalendar\b", lower) and any(
        w in lower for w in ("help", "status", "setup", "config")
    ):
        if calendar_tool.connected():
            return "Calendar is connected, sir. Try 'what's on my calendar today'."
        return calendar_tool.config_help()

    return None
