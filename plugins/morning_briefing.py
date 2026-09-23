"""Morning briefing - FatihMakes style startup routine."""

from jarvis.tools import system
from jarvis.tools.web_info import get_news, get_weather


def handle(text: str) -> str | None:
    lower = text.lower()
    triggers = (
        "morning briefing", "good morning", "brief me",
        "start my day", "daily briefing", "morning report",
    )
    if not any(t in lower for t in triggers):
        return None

    parts = [
        f"Good morning, sir. It is {system.get_time()}.",
        system.get_system_status(),
        get_weather(),
        get_news(3),
        "All systems operational. How may I assist you today?",
    ]
    return " ".join(parts)
