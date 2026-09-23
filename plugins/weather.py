"""Weather queries."""

from jarvis.tools.web_info import get_weather


def handle(text: str) -> str | None:
    lower = text.lower()
    if not any(w in lower for w in ("weather", "temperature", "forecast", "how hot", "how cold")):
        return None

    city = ""
    for prefix in ("weather in ", "forecast for ", "temperature in "):
        if prefix in lower:
            city = lower.split(prefix, 1)[1].strip().rstrip("?")
            break

    return get_weather(city)
