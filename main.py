#!/usr/bin/env python3
"""Jarvis - Full personal AI assistant for Windows."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from jarvis.brain import Brain
from jarvis.memory import Memory
from jarvis.plugins.loader import load_plugins, run_plugin_command
from jarvis.ui.hud import JarvisHUD
from jarvis.voice import Voice

console = Console()


def has_api_key() -> bool:
    env_keys = (
        "GROQ_API_KEY", "OPENROUTER_API_KEY", "NVIDIA_API_KEY",
        "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
    )
    if any(os.getenv(k) for k in env_keys):
        return True
    keys_file = ROOT / "config" / "api_keys.json"
    if keys_file.exists():
        try:
            keys = json.loads(keys_file.read_text(encoding="utf-8"))
            return any(keys.get(k) for k in ("groq", "openrouter", "nvidia", "anthropic", "gemini"))
        except json.JSONDecodeError:
            pass
    return False


def process_command(
    text: str, brain: Brain, voice: Voice, plugins: dict, hud: JarvisHUD | None,
) -> bool:
    """Process one command. Returns False if user wants to quit."""
    if not text:
        return True

    lower = text.lower()
    if any(w in lower for w in ("goodbye", "exit", "shut down jarvis", "stop jarvis")):
        voice.speak("Goodbye, sir. Jarvis going offline.")
        return False

    if hud:
        hud.show_user(text)
    if hud:
        hud.set_status("THINKING")

    plugin_response = run_plugin_command(plugins, text)
    if plugin_response:
        if hud:
            hud.show_jarvis(plugin_response)
        voice.speak(plugin_response)
        return True

    response = brain.think(text)
    if hud:
        hud.show_jarvis(response)
    voice.speak(response)
    return True


def run_full_mode(brain: Brain, voice: Voice, plugins: dict, wake_word: str) -> None:
    """Full Jarvis: HUD + always-listening voice + agent mode."""
    hud = JarvisHUD()
    voice.on_status = hud.set_status
    hud.start()

    voice.calibrate()
    voice.speak("Jarvis online. All systems operational. Awaiting your command, sir.")

    while True:
        try:
            text = voice.listen(wait_for_wake=True, wake_word=wake_word)
        except KeyboardInterrupt:
            break
        if not text:
            continue
        if not process_command(text, brain, voice, plugins, hud):
            break

    hud.stop()


def run_voice_mode(brain: Brain, voice: Voice, plugins: dict, wake_word: str) -> None:
    voice.calibrate()
    voice.speak("Jarvis online. How may I assist you?")
    while True:
        try:
            text = voice.listen()
        except KeyboardInterrupt:
            break
        if not text:
            continue
        if wake_word in text.lower():
            text = text.lower().replace(wake_word, "").strip()
        if not process_command(text, brain, voice, plugins, None):
            break


def run_text_mode(brain: Brain, voice: Voice, plugins: dict) -> None:
    console.print("[green]Text mode. Type commands (or 'quit').[/]")
    while True:
        try:
            user_input = console.input("[bold blue]You:[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit"):
            voice.speak("Goodbye, sir.")
            break
        process_command(user_input, brain, voice, plugins, None)


def main() -> None:
    settings_path = ROOT / "config" / "settings.json"
    with open(settings_path, encoding="utf-8") as f:
        settings = json.load(f)

    name = settings.get("assistant_name", "Jarvis")
    console.print(Panel(
        f"[bold cyan]{name}[/] — Personal AI Assistant\n"
        "[dim]Controls your PC by voice. Say 'Hey Jarvis' then your command.[/]",
        title="J.A.R.V.I.S MK-1", border_style="cyan",
    ))

    memory = Memory()
    user_name = os.getenv("JARVIS_USER_NAME", settings.get("user_name", "sir"))
    if not memory.get_user_name():
        memory.set_user_name(user_name)

    vs = settings.get("voice", {})
    brain = Brain(memory, assistant_name=name, user_name=user_name)

    hud_ref: list[JarvisHUD | None] = [None]
    voice = Voice(
        voice_id=os.getenv("JARVIS_VOICE", vs.get("voice_id", "en-GB-RyanNeural")),
        listen_timeout=vs.get("listen_timeout_seconds", 10),
        phrase_limit=vs.get("phrase_time_limit_seconds", 20),
        tts_engine=vs.get("tts_engine", "edge"),
    )

    plugins = load_plugins()
    console.print(f"[dim]Loaded {len(plugins)} plugin(s). Agent mode enabled.[/]")

    if not has_api_key():
        console.print(
            "[yellow]⚠ Add GROQ_API_KEY to .env for full AI control (free, no card).[/]\n"
            "[yellow]  https://console.groq.com/keys[/]"
        )

    mode = sys.argv[1].lower() if len(sys.argv) > 1 else "full"
    wake = vs.get("wake_word", "jarvis")

    if mode == "text":
        run_text_mode(brain, voice, plugins)
    elif mode == "voice":
        run_voice_mode(brain, voice, plugins, wake)
    else:
        console.print("[cyan]Launching full Jarvis mode (HUD + voice + PC control)...[/]")
        run_full_mode(brain, voice, plugins, wake)


if __name__ == "__main__":
    main()
