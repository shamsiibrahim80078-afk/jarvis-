"""Tool registry - all actions Jarvis can execute on the PC."""

from __future__ import annotations

from typing import Any, Callable

from jarvis.tools import system
from jarvis.tools.web_info import get_news, get_weather
from jarvis.tools.sheets import check_apis, open_google_sheet, sync_apis_to_env
from jarvis.tools.files_tool import copy_files, list_folder
from jarvis.tools.workflows import set_link

ToolFn = Callable[..., str]

TOOLS: dict[str, dict[str, Any]] = {
    "get_time": {"fn": lambda **_: system.get_time(), "params": []},
    "get_system_status": {"fn": lambda **_: system.get_system_status(), "params": []},
    "get_weather": {"fn": lambda city="": get_weather(city), "params": ["city"]},
    "get_news": {"fn": lambda **_: get_news(), "params": []},
    "open_app": {"fn": lambda app="": system.open_application(app), "params": ["app"]},
    "close_app": {"fn": lambda app="": system.close_application(app), "params": ["app"]},
    "list_windows": {"fn": lambda **_: system.list_open_windows(), "params": []},
    "open_website": {"fn": lambda url="": system.open_website(url), "params": ["url"]},
    "search_web": {"fn": lambda query="": system.search_web(query), "params": ["query"]},
    "open_youtube": {"fn": lambda query="": system.open_youtube(query), "params": ["query"]},
    "volume": {"fn": lambda action="up": system.set_volume(action), "params": ["action"]},
    "screenshot": {"fn": lambda **_: system.take_screenshot(), "params": []},
    "type_text": {"fn": lambda text="": system.type_text(text), "params": ["text"]},
    "press_keys": {"fn": lambda keys="": system.press_keys(keys), "params": ["keys"]},
    "run_command": {"fn": lambda command="": system.run_command(command), "params": ["command"]},
    "lock_screen": {"fn": lambda **_: system.lock_screen(), "params": []},
    "shutdown": {"fn": lambda action="shutdown": system.shutdown_pc(action), "params": ["action"]},
    "cancel_shutdown": {"fn": lambda **_: system.cancel_shutdown(), "params": []},
    "open_folder": {"fn": lambda path="": system.open_folder(path), "params": ["path"]},
    "create_file": {"fn": lambda path="", content="": system.create_file(path, content), "params": ["path", "content"]},
    "open_google_sheet": {"fn": lambda url="": open_google_sheet(url or None), "params": ["url"]},
    "check_apis": {"fn": lambda url="": check_apis(url or None), "params": ["url"]},
    "sync_apis_from_sheet": {"fn": lambda url="": sync_apis_to_env(url or None), "params": ["url"]},
    "copy_files": {"fn": lambda from_path="", to_path="": copy_files(from_path, to_path), "params": ["from_path", "to_path"]},
    "list_folder": {"fn": lambda path="": list_folder(path), "params": ["path"]},
    "save_link": {"fn": lambda name="", url="": set_link(name, url), "params": ["name", "url"]},
    "fetch_api_key": {
        "fn": lambda provider="", **_: __import__("jarvis.tools.api_hunter", fromlist=["fetch_api_key"]).fetch_api_key(f"get {provider} api key"),
        "params": ["provider"],
    },
    "batch_fetch_apis": {
        "fn": lambda **_: __import__("jarvis.tools.api_pipeline", fromlist=["run_batch_from_sheet"]).run_batch_from_sheet("get all apis from sheet"),
        "params": [],
    },
    "system_scan": {
        "fn": lambda **_: __import__("jarvis.tools.system_scanner", fromlist=["scan_and_fix"]).scan_and_fix("scan and fix"),
        "params": [],
    },
    "mira_create_image": {
        "fn": lambda topic="", style="cinematic", **_: __import__(
            "jarvis.tools.mira_tool", fromlist=["create_image"]
        ).create_image(topic, style),
        "params": ["topic", "style"],
    },
    "mira_create_video": {
        "fn": lambda topic="", duration_sec="30", aspect="16:9", script="", audio_mode="voice", media_paths="", use_uploads="", search_hints="", force_character="", mood="", format_key="", **_: __import__(
            "jarvis.tools.mira_tool", fromlist=["create_video"]
        ).create_video(topic, duration_sec, aspect, script, audio_mode, media_paths, use_uploads, search_hints, force_character, mood, format_key),
        "params": ["topic", "duration_sec", "aspect", "script", "audio_mode", "media_paths", "use_uploads", "search_hints", "force_character", "mood", "format_key"],
    },
    "mira_edit_video": {
        "fn": lambda aspect="", duration_sec="", start_sec="", speed="", mute="", volume="", text="", label="edit", **_: __import__(
            "jarvis.tools.mira_tool", fromlist=["edit_last_video"]
        ).edit_last_video(aspect, duration_sec, start_sec, speed, mute, volume, text, label),
        "params": ["aspect", "duration_sec", "start_sec", "speed", "mute", "volume", "text", "label"],
    },
    "mira_youtube_connect": {
        "fn": lambda **_: __import__(
            "jarvis.tools.mira_tool", fromlist=["youtube_connect"]
        ).youtube_connect(),
        "params": [],
    },
    "mira_youtube_upload": {
        "fn": lambda title="", privacy="unlisted", description="", **_: __import__(
            "jarvis.tools.mira_tool", fromlist=["youtube_upload_last"]
        ).youtube_upload_last(title, privacy, description),
        "params": ["title", "privacy", "description"],
    },
    "mira_rate": {
        "fn": lambda rating="4", topic="", note="", **_: __import__(
            "jarvis.tools.mira_tool", fromlist=["rate_media"]
        ).rate_media(rating, topic, note),
        "params": ["rating", "topic", "note"],
    },
  "mira_status": {
        "fn": lambda **_: __import__("jarvis.tools.mira_tool", fromlist=["mira_status"]).mira_status(),
        "params": [],
    },
    "mira_office_day": {
        "fn": lambda day="", duration_sec="45", aspect="16:9", language="en", audio_mode="voice", **_: __import__(
            "jarvis.tools.mira_tool", fromlist=["create_office_day"]
        ).create_office_day(day, duration_sec, aspect, language, audio_mode),
        "params": ["day", "duration_sec", "aspect", "language", "audio_mode"],
    },
}


def execute_tool(name: str, params: dict[str, str], memory_remember: Callable[[str], None] | None = None) -> str:
    if name == "remember":
        fact = params.get("fact", "")
        if fact and memory_remember:
            memory_remember(fact)
            return f"I'll remember that, sir: {fact}"
        return "Nothing to remember."

    tool = TOOLS.get(name)
    if not tool:
        return f"Unknown tool: {name}"

    fn: ToolFn = tool["fn"]
    kwargs = {k: params.get(k, "") for k in tool["params"]}
    return fn(**kwargs)


def tools_description() -> str:
    lines = []
    for name, info in TOOLS.items():
        params = ", ".join(info["params"]) or "none"
        lines.append(f"- {name} (params: {params})")
    lines.append('- remember (params: fact) - save to long-term memory')
    return "\n".join(lines)
