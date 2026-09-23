"""PC control — always opens websites in Google Chrome."""

from __future__ import annotations

import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from urllib.parse import quote

import psutil
import pyautogui

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05

ROOT = Path(__file__).resolve().parents[2]
SCREENSHOT_DIR = ROOT / "data" / "screenshots"

CHROME_PATHS = [
    os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
]

APP_MAP: dict[str, str] = {
    "notepad": "notepad",
    "calculator": "calc",
    "calc": "calc",
    "chrome": "chrome",
    "firefox": "firefox",
    "edge": "msedge",
    "explorer": "explorer",
    "file explorer": "explorer",
    "files": "explorer",
    "cmd": "cmd",
    "command prompt": "cmd",
    "powershell": "powershell",
    "spotify": "spotify",
    "discord": "discord",
    "vscode": "code",
    "cursor": "cursor",
    "settings": "ms-settings:",
    "task manager": "taskmgr",
    "paint": "mspaint",
}


def find_chrome() -> str | None:
    for path in CHROME_PATHS:
        if os.path.isfile(path):
            return path
    return None


def open_in_chrome(url: str = "https://google.com", new_window: bool = False) -> str:
    """Open URL in Chrome — reuses existing window by default (no spam tabs)."""
    chrome = find_chrome()
    if not chrome:
        import webbrowser
        webbrowser.open(url)
        return f"Chrome not found. Opened in default browser: {url}"

    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    args = [chrome]
    if new_window:
        args.append("--new-window")
    args.append(url)

    subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )
    try:
        from jarvis.tools.api_intent import remember_site
        remember_site(url)
    except Exception:
        pass
    return f"Opening in Chrome, sir."


def search_in_chrome(query: str) -> str:
    url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
    return open_in_chrome(url)


def open_youtube_in_chrome(query: str = "") -> str:
    import re

    from jarvis.context import set_context

    q = (query or "").strip()
    # Refuse generate / upload intents (should go to Mira)
    if q and re.search(
        r"\b(make|create|generate|render)\b.{0,40}\b(video|image|clip)\b|"
        r"\b(upload|post|publish)\b.{0,40}\byoutube\b|"
        r"\b(post|upload)\s+(?:this|it|last|that|the)\s+(?:video|clip|short|reel)\b",
        q,
        re.I,
    ):
        from jarvis.tools.mira_tool import try_mira_command

        mira = try_mira_command(q, background=True)
        if mira:
            return mira

    if q:
        url = f"https://www.youtube.com/results?search_query={quote(q)}"
        set_context("youtube", last_query=q)
        open_in_chrome(url)
        return f"Searching YouTube for '{q}', sir."
    url = "https://www.youtube.com"
    set_context("youtube")
    return open_in_chrome(url)


def get_time() -> str:
    return datetime.now().strftime("%I:%M %p on %A, %B %d, %Y")


def get_system_status() -> str:
    cpu = psutil.cpu_percent(interval=0)
    mem = psutil.virtual_memory()
    parts = [f"CPU {cpu:.0f} percent", f"Memory {mem.percent:.0f} percent"]
    return ". ".join(parts) + "."


def open_application(name: str) -> str:
    key = name.strip().lower()
    if key == "chrome":
        return open_in_chrome()
    if key in APP_MAP:
        cmd = APP_MAP[key]
        try:
            if cmd.endswith(":"):
                os.startfile(cmd)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(
                    [cmd], shell=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            return f"Opening {name}, sir."
        except OSError as exc:
            return f"Could not open {name}: {exc}"
    return open_in_chrome(f"https://www.google.com/search?q={name.replace(' ', '+')}")


def close_application(name: str) -> str:
    import pygetwindow as gw
    key = name.strip().lower()
    closed = 0
    for win in gw.getAllWindows():
        if key in win.title.lower():
            try:
                win.close()
                closed += 1
            except Exception:
                pass
    return f"Closed {closed} window(s), sir." if closed else f"No window found for {name}."


def list_open_windows() -> str:
    import pygetwindow as gw
    titles = [w.title for w in gw.getAllWindows() if w.title.strip()][:10]
    return "Open windows: " + "; ".join(titles) if titles else "No visible windows."


def open_website(url: str) -> str:
    return open_in_chrome(url)


def search_web(query: str) -> str:
    return search_in_chrome(query)


def open_youtube(query: str = "") -> str:
    return open_youtube_in_chrome(query)


def set_volume(action: str) -> str:
    action = action.lower()
    if action in ("up", "increase", "louder"):
        pyautogui.press("volumeup", presses=5)
        return "Volume up, sir."
    if action in ("down", "decrease", "quieter"):
        pyautogui.press("volumedown", presses=5)
        return "Volume down, sir."
    if action in ("mute", "silence"):
        pyautogui.press("volumemute")
        return "Muted, sir."
    return "Say volume up, down, or mute."


def take_screenshot() -> str:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SCREENSHOT_DIR / f"screen_{int(time.time())}.png"
    pyautogui.screenshot().save(str(path))
    return f"Screenshot saved, sir."


def type_text(text: str) -> str:
    import pyperclip
    pyperclip.copy(text)
    pyautogui.hotkey("ctrl", "v")
    return "Done, sir."


def press_keys(keys: str) -> str:
    pyautogui.hotkey(*keys.split("+"))
    return "Done, sir."


def run_command(command: str) -> str:
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=15)
        return (result.stdout or result.stderr or "Done.").strip()[:300]
    except Exception as exc:
        return f"Failed: {exc}"


def lock_screen() -> str:
    subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"], check=False)
    return "Locked, sir."


def shutdown_pc(action: str = "shutdown") -> str:
    flag = "/r" if action.lower() in ("restart", "reboot") else "/s"
    subprocess.Popen(["shutdown", flag, "/t", "5"])
    return "Shutting down in 5 seconds, sir."


def cancel_shutdown() -> str:
    subprocess.run(["shutdown", "/a"], check=False)
    return "Cancelled, sir."


def open_folder(path: str) -> str:
    p = Path(path).expanduser()
    if not p.exists():
        return f"Folder not found: {path}"
    os.startfile(str(p))  # type: ignore[attr-defined]
    return f"Opened, sir."


def create_file(path: str, content: str = "") -> str:
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"File created, sir."
