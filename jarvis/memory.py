"""Persistent memory for Jarvis (Luke/Claude-style MEMORY.md pattern)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MEMORY_PATH = ROOT / "data" / "memory.json"


class Memory:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DEFAULT_MEMORY_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "user": {},
                "facts": [],
                "conversations": [],
                "preferences": {},
            }
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"user": {}, "facts": [], "conversations": [], "preferences": {}}

    def save(self) -> None:
        self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    def remember_fact(self, fact: str) -> None:
        entry = {
            "fact": fact.strip(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._data.setdefault("facts", []).append(entry)
        # Keep last 100 facts
        self._data["facts"] = self._data["facts"][-100:]
        self.save()

    def set_user_name(self, name: str) -> None:
        self._data.setdefault("user", {})["name"] = name.strip()
        self.save()

    def get_user_name(self) -> str | None:
        return self._data.get("user", {}).get("name")

    def add_conversation(self, user: str, assistant: str) -> None:
        self._data.setdefault("conversations", []).append(
            {
                "user": user,
                "assistant": assistant,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        self._data["conversations"] = self._data["conversations"][-50:]
        self.save()

    def get_context_prompt(self, max_items: int = 20) -> str:
        lines: list[str] = []
        user_name = self.get_user_name()
        if user_name:
            lines.append(f"User's name is {user_name}.")

        facts = self._data.get("facts", [])[-max_items:]
        if facts:
            lines.append("Known facts about the user:")
            for item in facts:
                lines.append(f"- {item['fact']}")

        prefs = self._data.get("preferences", {})
        if prefs:
            lines.append("User preferences:")
            for key, value in prefs.items():
                lines.append(f"- {key}: {value}")

        recent = self._data.get("conversations", [])[-5:]
        if recent:
            lines.append("Recent conversation:")
            for turn in recent:
                lines.append(f"User: {turn['user']}")
                lines.append(f"Assistant: {turn['assistant']}")

        return "\n".join(lines)
