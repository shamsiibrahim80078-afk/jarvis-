"""Unprompted agent chatter — keeps the floor feeling alive."""

from __future__ import annotations

import logging
import random
import threading
import time

from jarvis.crew import bus

logger = logging.getLogger(__name__)

_stop = threading.Event()
_thread: threading.Thread | None = None

_LINES = [
    ("jarvis", "mira", "Intercom — Mira, my office when free."),
    ("mira", "jarvis", "On my way to your cabin, Adrian."),
    ("jarvis", "hunter", "Kai — step into the boss cabin."),
    ("hunter", "jarvis", "Coming to your office now."),
    ("mail", "waiter", "Intercom: Ravi, coffee to Inbox."),
    ("waiter", "mail", "Copy Priya — tray walking."),
    ("mira", "waiter", "Intercom: water bottles for Studio."),
    ("waiter", "mira", "On it — pantry to Studio."),
    ("jarvis", "waiter", "Intercom: lunch trays for the floor."),
    ("waiter", "jarvis", "Serving now, Adrian."),
    ("calendar", "waiter", "Intercom: tea for Cal desk."),
    ("weather", "jarvis", "Nora ready if you need a brief in cabin."),
    ("briefing", "jarvis", "Morning pack ready for your office."),
    ("youtube", "jarvis", "Diego standing by for a cabin call."),
    ("jarvis", "owner", "Boss cabin live. I call staff in, then they execute."),
    ("guard1", "guard2", "Gate clear — employees only."),
]


def _tick() -> None:
    st = bus.get_state()
    agents = st.get("agents") or {}
    if any((a or {}).get("status") == "working" for a in agents.values()):
        return
    a, b, line = random.choice(_LINES)
    bus.emit("chat", from_id=a, to_id=b, text=line)


def _loop() -> None:
    logger.info("Crew ambient chatter started")
    while not _stop.is_set():
        try:
            _tick()
        except Exception as exc:
            logger.debug("ambient tick: %s", exc)
        _stop.wait(random.uniform(22.0, 40.0))
    logger.info("Crew ambient chatter stopped")


def start_ambient() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, daemon=True, name="crew-ambient")
    _thread.start()


def stop_ambient() -> None:
    _stop.set()
