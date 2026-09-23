"""Crew registry — agents as real people on the Nexus HQ floor."""

from __future__ import annotations

from typing import Any

# Each agent is a person: full name, role, personality — not a floating label.
AGENTS: dict[str, dict[str, Any]] = {
    "jarvis": {
        "id": "jarvis",
        "name": "Adrian Cole",
        "first_name": "Adrian",
        "codename": "Jarvis",
        "role": "Boss · Floor Manager",
        "title": "Managing Director · Nexus HQ",
        "station": "Boss",
        "color": "#22d3ee",
        "persona": "Suit-and-coat boss — calls people into his cabin, then they execute.",
        "skills": ["routing", "oversight", "owner_chat", "pc", "briefing_staff"],
        "status": "online",
        "activity": "In the boss cabin",
    },
    "hunter": {
        "id": "hunter",
        "name": "Kai Morales",
        "first_name": "Kai",
        "codename": "Hunter",
        "role": "API Scout",
        "title": "Credentials & Keys Specialist",
        "station": "Keys",
        "color": "#f59e0b",
        "persona": "Fast fingers, lives in Chrome — finds API keys before coffee cools.",
        "skills": ["api", "keys", "login", "chrome", "env"],
        "status": "idle",
        "activity": "Ready to hunt keys",
    },
    "mira": {
        "id": "mira",
        "name": "Mira Chen",
        "first_name": "Mira",
        "codename": "Mira",
        "role": "Creative Director",
        "title": "Video & Shorts Producer",
        "station": "Studio",
        "color": "#a78bfa",
        "persona": "Visual storyteller — hooks, cuts, and publishes with taste.",
        "skills": [
            "video",
            "shorts",
            "youtube",
            "clipping",
            "growth",
            "image",
            "reels",
        ],
        "status": "idle",
        "activity": "Ready for a brief",
    },
    "weather": {
        "id": "weather",
        "name": "Nora Blake",
        "first_name": "Nora",
        "codename": "Sky",
        "role": "Weather Analyst",
        "title": "Climate Desk",
        "station": "Sky",
        "color": "#38bdf8",
        "persona": "Quiet focus — always knows if you need an umbrella.",
        "skills": ["weather", "forecast", "temperature"],
        "status": "idle",
        "activity": "Watching the skies",
    },
    "mail": {
        "id": "mail",
        "name": "Priya Kapoor",
        "first_name": "Priya",
        "codename": "Post",
        "role": "Communications",
        "title": "Inbox & Outreach Lead",
        "station": "Inbox",
        "color": "#f472b6",
        "persona": "Polished writer — inbox zero is a lifestyle.",
        "skills": ["email", "gmail", "inbox", "send"],
        "status": "idle",
        "activity": "Inbox clear",
    },
    "calendar": {
        "id": "calendar",
        "name": "Ethan Brooks",
        "first_name": "Ethan",
        "codename": "Cal",
        "role": "Scheduler",
        "title": "Calendar & Meetings Lead",
        "station": "Cal",
        "color": "#4ade80",
        "persona": "Never double-books — time is his craft.",
        "skills": ["calendar", "schedule", "events", "meetings"],
        "status": "idle",
        "activity": "Schedule open",
    },
    "youtube": {
        "id": "youtube",
        "name": "Diego Santos",
        "first_name": "Diego",
        "codename": "Tube",
        "role": "Media Runner",
        "title": "YouTube Desk",
        "station": "Tube",
        "color": "#ef4444",
        "persona": "Opens the right video in seconds — always plugged in.",
        "skills": ["youtube", "search", "watch"],
        "status": "idle",
        "activity": "Ready to open YouTube",
    },
    "briefing": {
        "id": "briefing",
        "name": "Sam Okonkwo",
        "first_name": "Sam",
        "codename": "Brief",
        "role": "Briefing Officer",
        "title": "Morning Intelligence",
        "station": "Brief",
        "color": "#eab308",
        "persona": "Starts your day with news, weather, and system pulse.",
        "skills": ["briefing", "news", "morning", "report"],
        "status": "idle",
        "activity": "Briefing stacked",
    },
    "waiter": {
        "id": "waiter",
        "name": "Ravi Mehta",
        "first_name": "Ravi",
        "codename": "Service",
        "role": "Office Waiter",
        "title": "Pantry & Service",
        "station": "Pantry",
        "color": "#f5f5f4",
        "persona": "Called on intercom for lunch, bottles, coffee — always with a tray.",
        "skills": ["lunch", "coffee", "water", "bottles", "service", "pantry"],
        "status": "idle",
        "activity": "Pantry ready",
    },
}


def list_agents() -> list[dict[str, Any]]:
    return [dict(a) for a in AGENTS.values()]


def get_agent(agent_id: str) -> dict[str, Any] | None:
    a = AGENTS.get((agent_id or "").strip().lower())
    return dict(a) if a else None


def display_name(agent_id: str) -> str:
    a = AGENTS.get((agent_id or "").strip().lower()) or {}
    return a.get("name") or a.get("first_name") or (agent_id or "Agent").title()


def pick_agent_for_task(text: str) -> str:
    """Jarvis chooses which worker owns this owner command."""
    t = (text or "").lower()

    # Explicit person call wins first (e.g. "Mira make a short about coffee")
    named = (
        ("mira", ("mira chen", "mira",)),
        ("hunter", ("kai morales", "kai", "hunter",)),
        ("weather", ("nora blake", "nora",)),
        ("mail", ("priya kapoor", "priya",)),
        ("calendar", ("ethan brooks", "ethan",)),
        ("youtube", ("diego santos", "diego",)),
        ("briefing", ("sam okonkwo", "sam",)),
        ("waiter", ("ravi mehta", "ravi", "waiter",)),
        ("jarvis", ("adrian cole", "adrian", "jarvis",)),
    )
    for aid, keys in named:
        if any(k in t for k in keys):
            return aid

    # Mira domain (video/shorts) — before waiter so "short about coffee" ≠ pantry
    mira_keys = (
        "video", "short", "shorts", "reel", "clip", "clipping",
        "growth", "viral", "tiktok", "image", "picture", "photo",
        "schedule shorts", "export to reels", "analytics", "make a short",
        "post viral", "post a short", "youtube short",
    )
    if any(k in t for k in mira_keys):
        return "mira"
    if "schedule" in t and any(k in t for k in ("short", "shorts", "reel", "viral")):
        return "mira"
    if "upload" in t and any(k in t for k in ("video", "short", "reel", "mira")):
        return "mira"

    # API Hunter
    hunt_keys = (
        "api key", "api keys", "fetch api", "grab api", "get api", "get me the api",
        "sign in", "login", "save to .env", "save to env",
    )
    providers = (
        "groq", "fish", "eleven", "11 labs", "openrouter", "nvidia", "gemini",
        "anthropic", "openai", "claude", "cursor", "together", "hugging", "deepseek",
    )
    if any(k in t for k in hunt_keys):
        return "hunter"
    if any(p in t for p in providers) and any(w in t for w in ("api", "key", "keys", "get", "fetch", "grab")):
        return "hunter"

    # Morning briefing
    if any(k in t for k in ("morning briefing", "good morning", "brief me", "start my day", "daily briefing", "morning report")):
        return "briefing"

    # Weather
    if any(k in t for k in ("weather", "temperature", "forecast", "how hot", "how cold")):
        return "weather"

    # Mail
    if any(k in t for k in ("email", "gmail", "inbox", "unread", "send mail", "send email", "check mail")):
        return "mail"

    # Calendar
    if any(k in t for k in ("calendar", "my schedule", "meetings", "what's on my calendar", "create event", "add event")):
        return "calendar"

    # YouTube open/search (not Mira generate)
    if "youtube" in t or ("open" in t and "video" in t and "make" not in t):
        return "youtube"

    # Waiter / pantry — after creative/work skills so coffee in a Short stays Mira
    if any(k in t for k in (
        "lunch", "coffee", "tea", "water bottle", "bottles", "bring lunch",
        "serve", "pantry", "intercom", "hungry", "snack", "bring water",
    )):
        return "waiter"

    return "jarvis"
