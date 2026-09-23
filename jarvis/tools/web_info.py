"""Fetch weather and news - no API key needed."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import requests

_WMO = {
    0: "Clear",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Dense drizzle",
    61: "Slight rain",
    63: "Rain",
    65: "Heavy rain",
    71: "Slight snow",
    73: "Snow",
    75: "Heavy snow",
    80: "Rain showers",
    81: "Rain showers",
    82: "Violent rain showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail",
    99: "Thunderstorm with heavy hail",
}

# Default when no city given (Islamabad) — IP geo is often blocked.
_DEFAULT_LAT, _DEFAULT_LON, _DEFAULT_NAME = 33.6844, 73.0479, "Islamabad"


def _weather_open_meteo(city: str = "") -> str:
    name = (city or "").strip() or _DEFAULT_NAME
    lat, lon = _DEFAULT_LAT, _DEFAULT_LON
    if city.strip():
        geo = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city.strip(), "count": 1, "language": "en", "format": "json"},
            timeout=8,
            headers={"User-Agent": "Jarvis/1.0"},
        )
        geo.raise_for_status()
        results = (geo.json() or {}).get("results") or []
        if not results:
            raise ValueError(f"Unknown city: {city}")
        hit = results[0]
        lat = float(hit["latitude"])
        lon = float(hit["longitude"])
        name = hit.get("name") or name
        country = hit.get("country_code") or ""
        if country:
            name = f"{name}, {country}"

    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code",
        },
        timeout=8,
        headers={"User-Agent": "Jarvis/1.0"},
    )
    r.raise_for_status()
    cur = (r.json() or {}).get("current") or {}
    temp = cur.get("temperature_2m", "?")
    feels = cur.get("apparent_temperature", temp)
    humidity = cur.get("relative_humidity_2m", "?")
    code = cur.get("weather_code")
    desc = _WMO.get(int(code), "Unknown") if code is not None else "Unknown"
    return (
        f"Weather in {name}: {desc}, {temp} degrees Celsius, "
        f"feels like {feels}, humidity {humidity} percent."
    )


def _weather_wttr(city: str = "") -> str:
    loc = city.replace(" ", "+") if city else ""
    url = f"https://wttr.in/{loc}?format=j1" if loc else "https://wttr.in/?format=j1"
    r = requests.get(url, timeout=6, headers={"User-Agent": "Jarvis/1.0"})
    r.raise_for_status()
    data = r.json()
    cur = data["current_condition"][0]
    area = data.get("nearest_area", [{}])[0]
    name = area.get("areaName", [{}])[0].get("value", city or "your location")
    temp = cur.get("temp_C", "?")
    desc = cur.get("weatherDesc", [{}])[0].get("value", "")
    feels = cur.get("FeelsLikeC", temp)
    humidity = cur.get("humidity", "?")
    return (
        f"Weather in {name}: {desc}, {temp} degrees Celsius, "
        f"feels like {feels}, humidity {humidity} percent."
    )


def get_weather(city: str = "") -> str:
    """Prefer Open-Meteo (reliable); fall back to wttr.in."""
    errors: list[str] = []
    try:
        return _weather_open_meteo(city)
    except Exception as exc:
        errors.append(f"open-meteo: {exc}")
    try:
        return _weather_wttr(city)
    except Exception as exc:
        errors.append(f"wttr: {exc}")
    return f"Could not fetch weather: {'; '.join(errors)}"


def get_news(headlines: int = 5) -> str:
    try:
        r = requests.get(
            "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
            timeout=8,
            headers={"User-Agent": "Jarvis/1.0"},
        )
        root = ET.fromstring(r.content)
        items = []
        for item in root.findall(".//item")[:headlines]:
            title = item.find("title")
            if title is not None and title.text:
                items.append(title.text)
        if not items:
            return "No headlines available."
        return "Top headlines: " + ". ".join(items)
    except Exception as exc:
        return f"Could not fetch news: {exc}"
