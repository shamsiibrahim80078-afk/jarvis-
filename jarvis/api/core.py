"""Shared Jarvis core instance for API server."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv

from jarvis.brain import Brain
from jarvis.fast_router import (
    is_human_view_command,
    is_wake_only,
    try_fast_command,
)
from jarvis.tools.api_hunter import fetch_api_key
from jarvis.tools.api_intent import is_api_hunt_intent
from jarvis.tools.api_pipeline import (
    count_apis_from_sheet,
    is_api_count_command,
    is_batch_api_command,
    paste_apis_to_sheet,
    run_batch_from_sheet,
)
from jarvis.memory import Memory
from jarvis.plugins.loader import load_plugins, run_plugin_command
from jarvis.tools import system
from jarvis.tools.task_executor import try_task_command
from jarvis.tools.web_info import get_news, get_weather
from jarvis.tools.command_parse import (
    is_sheet_context_command,
    normalize,
)
from jarvis.tools.screen_share import (
    answer_with_vision,
    handle_screen_share_command,
    is_screen_share_command,
    should_use_vision,
)

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


class JarvisCore:
    def __init__(self) -> None:
        settings_path = ROOT / "config" / "settings.json"
        with open(settings_path, encoding="utf-8") as f:
            self.settings = json.load(f)

        self.memory = Memory()
        user_name = os.getenv("JARVIS_USER_NAME", self.settings.get("user_name", "sir"))
        if not self.memory.get_user_name():
            self.memory.set_user_name(user_name)

        name = os.getenv("JARVIS_NAME", self.settings.get("assistant_name", "Jarvis"))
        self.brain = Brain(self.memory, assistant_name=name, user_name=user_name)
        self.plugins = load_plugins()

    def process(self, text: str) -> dict:
        text = text.strip()
        if not text:
            return {"response": "I didn't catch that, sir.", "source": "system"}

        # Hard guards — these NEVER reach the LLM brain
        if is_wake_only(text):
            return {"response": "Yes sir, how may I help you?", "source": "wake"}

        from jarvis import autonomy

        if autonomy.is_illegal(text):
            return {"response": autonomy.illegal_message(), "source": "autonomy"}

        confirmed = autonomy.take_pending_if_confirmed(text)
        if confirmed:
            text = confirmed
        elif autonomy.is_hard_pause(text):
            return {"response": autonomy.pause_message(text), "source": "autonomy"}

        # Plain fact memory — never LLM (links/sheets still use task path below)
        low = text.lower()
        if (
            (low.startswith("remember that ") or low.startswith("remember "))
            and "http://" not in low
            and "https://" not in low
            and "sheet" not in low
            and "gid" not in low
            and ":\\" not in text
        ):
            fact = text.split(" ", 1)[1] if " " in text else ""
            if fact.lower().startswith("that "):
                fact = fact[5:]
            fact = fact.strip(" .")
            if fact:
                self.memory.remember_fact(fact)
                reply = f"I'll remember that, sir: {fact}."
                self.memory.add_conversation(text, reply)
                return {"response": reply, "source": "memory"}

        # Remember sheet/link before hunt (avoids "my api sheet" → hunter)
        if "remember" in low:
            task = try_task_command(text)
            if task:
                return {"response": task, "source": "task"}

        if is_api_count_command(text):
            return {"response": count_apis_from_sheet(text), "source": "api_count"}

        if is_batch_api_command(text):
            lower = normalize(text)
            if ("paste" in lower or "put" in lower) and not re.search(r"\b(get|fetch|grab|fill)\b", lower):
                return {"response": paste_apis_to_sheet(text), "source": "sheet_batch"}
            return {"response": run_batch_from_sheet(text), "source": "sheet_batch"}

        if is_api_hunt_intent(text):
            return {"response": fetch_api_key(text), "source": "api_hunt"}

        # Mira generate — before YouTube/search/brain (any topic; no need to say "mira")
        from jarvis.tools.mira_tool import try_mira_command

        mira_out = try_mira_command(text, background=True)
        if mira_out:
            self.memory.add_conversation(text, mira_out)
            return {"response": mira_out, "source": "mira"}

        if is_human_view_command(text):
            system.open_in_chrome("http://127.0.0.1:8765/face")
            return {"response": "Opening the human interface, sir.", "source": "fast"}

        if is_screen_share_command(text):
            result = handle_screen_share_command(text)
            if result:
                return {"response": result, "source": "screen_share"}

        # Sheet / Veridiq tab commands — NEVER brain
        if is_sheet_context_command(text):
            fast = try_fast_command(text)
            if fast:
                return {"response": fast, "source": "fast"}
            task = try_task_command(text)
            if task:
                return {"response": task, "source": "task"}

        # ⚡ Instant — no AI delay
        fast = try_fast_command(text)
        if fast:
            return {"response": fast, "source": "fast"}

        # 🔗 Multi-step tasks, links, sheets, file transfers
        task = try_task_command(text)
        if task:
            return {"response": task, "source": "task"}

        plugin_response = run_plugin_command(self.plugins, text)
        if plugin_response:
            return {"response": plugin_response, "source": "plugin"}

        # Vision: when user is sharing screen, use latest frame
        if should_use_vision(text):
            try:
                vision = answer_with_vision(text)
                return {"response": vision, "source": "vision"}
            except Exception:
                pass

        response = self.brain.think(text)
        return {"response": response, "source": "brain"}

    def get_status(self) -> dict:
        import psutil

        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("C:\\")
        battery = None
        try:
            if hasattr(psutil, "sensors_battery"):
                bat = psutil.sensors_battery()
                if bat:
                    battery = bat.percent
        except Exception:
            battery = None

        return {
            "time": system.get_time(),
            "cpu": round(float(cpu or 0), 1),
            "memory": round(mem.percent, 1),
            "disk": round(disk.percent, 1),
            "battery": battery,
            "plugins": list(self.plugins.keys()),
            "user": self.memory.get_user_name() or "sir",
            "online": True,
        }

    def get_briefing(self) -> str:
        parts = [
            f"Good morning, sir. It is {system.get_time()}.",
            system.get_system_status(),
            get_weather(),
            get_news(3),
            "All systems operational.",
        ]
        return " ".join(parts)


# Singleton
_core: JarvisCore | None = None
_status_cache: dict = {"t": 0.0, "data": None}


def get_core() -> JarvisCore:
    global _core
    if _core is None:
        _core = JarvisCore()
    return _core


def get_status_cached() -> dict:
    """Light cached status so HUD polling never starves API commands."""
    import time

    global _status_cache
    now = time.time()
    if _status_cache["data"] is not None and now - _status_cache["t"] < 2.5:
        return _status_cache["data"]
    data = get_core().get_status()
    _status_cache = {"t": now, "data": data}
    return data
