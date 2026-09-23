"""Crew dispatcher — owner command → Jarvis routes → worker executes (live)."""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from jarvis.crew import bus
from jarvis.crew.registry import display_name, get_agent, pick_agent_for_task

logger = logging.getLogger(__name__)


def dispatch_owner_command(text: str, *, source: str = "owner") -> dict[str, Any]:
    """Owner speaks → Jarvis assigns → agent works. Returns ack for UI."""
    raw = (text or "").strip()
    if not raw:
        return {"ok": False, "message": "Empty command."}

    agent_id = pick_agent_for_task(raw)
    agent = get_agent(agent_id) or {}
    agent_name = agent.get("name") or display_name(agent_id)
    first = agent.get("first_name") or agent_name.split()[0]
    station = agent.get("station") or "desk"
    title = agent.get("title") or agent.get("role") or ""

    bus.emit(
        "chat",
        from_id="owner" if source == "owner" else "jarvis",
        to_id="jarvis",
        text=raw,
    )

    if agent_id == "jarvis":
        bus.emit(
            "chat",
            from_id="jarvis",
            to_id="owner",
            text="I'll handle that myself from the command floor.",
        )
        bus.set_agent_status("jarvis", "working", f"Handling: {raw[:70]}")
        return {
            "ok": True,
            "agent_id": "jarvis",
            "routed": False,
            "message": "Jarvis will handle this on the command floor.",
            "handle_locally": True,
        }

    # Assign worker — live: Adrian calls them into the boss cabin first
    task = bus.create_task(raw[:120], agent_id=agent_id, owner_text=raw)
    bus.emit(
        "chat",
        from_id="jarvis",
        to_id=agent_id,
        text=f"Intercom — {first}, my office. Now.",
        task_id=task["id"],
        extra={"briefing": True, "office": "boss"},
    )
    bus.set_agent_status("jarvis", "working", f"Briefing {first} in boss cabin", task_id=task["id"])
    bus.set_agent_status(agent_id, "working", f"Called to boss cabin", task_id=task["id"])
    bus.emit(
        "chat",
        from_id=agent_id,
        to_id="jarvis",
        text=f"On my way to your cabin, Adrian.",
        task_id=task["id"],
    )
    bus.emit(
        "chat",
        from_id="jarvis",
        to_id=agent_id,
        text=f"Brief: {raw[:140]}",
        task_id=task["id"],
    )

    runner = _RUNNERS.get(agent_id)
    if not runner:
        bus.update_task(task["id"], status="blocked", result="Agent not wired yet")
        bus.set_agent_status(agent_id, "idle", "Waiting for skills", task_id=None)
        return {
            "ok": False,
            "agent_id": agent_id,
            "message": f"Agent {agent_name} is registered but not online yet.",
            "handle_locally": True,
        }

    # Fast desks run sync so Owner gets the answer; Mira/Hunter stay live background
    fast = agent_id in ("weather", "youtube", "briefing", "calendar", "mail", "waiter")
    if fast:
        runner(task["id"], raw)
        st = bus.get_state()
        result_text = ""
        for t in reversed(st.get("tasks") or []):
            if t.get("id") == task["id"]:
                result_text = t.get("result") or ""
                break
        return {
            "ok": True,
            "agent_id": agent_id,
            "task_id": task["id"],
            "routed": True,
            "message": result_text or f"{agent_name} finished.",
            "response": result_text or f"{agent_name} finished.",
            "handle_locally": False,
            "poll": False,
        }

    threading.Thread(
        target=runner,
        args=(task["id"], raw),
        daemon=True,
        name=f"crew-{agent_id}",
    ).start()

    return {
        "ok": True,
        "agent_id": agent_id,
        "task_id": task["id"],
        "routed": True,
            "message": (
                f"Adrian assigned {agent_name} ({title or station}). "
                "Watch Agent Town — they walk to their cabin and work live."
            ),
            "response": (
                f"Adrian Cole assigned {agent_name} · {title or station}. "
                "Watch them work live on the floor."
            ),
        "handle_locally": False,
        "poll": agent_id in ("mira", "hunter"),
    }


def _finish_ok(agent_id: str, task_id: str, text: str, idle_line: str) -> None:
    text = (text or "Done.")[:600]
    bus.update_task(task_id, status="done", result=text)
    bus.set_agent_status(agent_id, "idle", idle_line, task_id=None)
    bus.emit("chat", from_id=agent_id, to_id="jarvis", text=f"Done — {text[:180]}", task_id=task_id)
    name = display_name(agent_id)
    bus.emit(
        "chat",
        from_id="jarvis",
        to_id="owner",
        text=f"{name} finished. {text[:160]}",
        task_id=task_id,
    )


def _finish_err(agent_id: str, task_id: str, exc: Exception) -> None:
    logger.exception("%s crew task failed", agent_id)
    bus.update_task(task_id, status="error", result=str(exc)[:300])
    bus.set_agent_status(agent_id, "idle", "Recovered — ready", task_id=None)
    bus.emit(
        "chat",
        from_id=agent_id,
        to_id="jarvis",
        text=f"Hit a snag: {str(exc)[:140]}",
        task_id=task_id,
    )


def _prog(agent_id: str, task_id: str, msg: str) -> None:
    bus.set_agent_status(agent_id, "working", msg[:120], task_id=task_id)
    bus.emit("progress", from_id=agent_id, to_id="jarvis", text=msg[:200], task_id=task_id)


def _run_mira_task(task_id: str, raw: str) -> None:
    try:
        bus.update_task(task_id, status="running")
        _prog("mira", task_id, "In the studio…")

        from pathlib import Path

        from jarvis.tools import mira_jobs
        from jarvis.tools.mira_tool import (
            media_url_for_path,
            parse_mira_command,
            run_parsed_action,
            try_mira_command,
        )

        # Drive HUD mira-status so Owner sees live progress (not a stale "Video ready")
        q = (raw or "mira")[:200]
        plat_id = ""
        try:
            from jarvis.mira.platforms import detect_platform

            plat = detect_platform(raw)
            if plat:
                plat_id = str(plat.get("id") or "")
        except Exception:
            pass
        job_id = mira_jobs.set_running(q, platform=plat_id)
        if not job_id:
            _finish_ok(
                "mira",
                task_id,
                "Mira is already busy — wait for the current job.",
                "Busy",
            )
            return

        orig = mira_jobs.set_progress

        def bridged_fixed(message: str, **kwargs: object) -> None:
            jid = kwargs.get("job_id") if isinstance(kwargs.get("job_id"), str) else job_id
            orig(message, job_id=str(jid or job_id))
            _prog("mira", task_id, message)

        mira_jobs.set_progress = bridged_fixed  # type: ignore[assignment]
        result = "Mira finished."
        media_path = None
        media_url = None
        try:
            parsed = None
            try:
                parsed = parse_mira_command(raw)
            except Exception:
                parsed = None
            if parsed and parsed.get("action") in ("video", "image", "office_day", "edit", "remake"):
                # Never downgrade a live platform tour to Shorts defaults
                if parsed.get("action") == "video" and not parsed.get("platform_tour"):
                    parsed.setdefault("aspect", "9:16")
                    parsed.setdefault("format", "youtube_shorts")
                    parsed.setdefault("duration_sec", "20")
                if parsed.get("platform_tour"):
                    mira_jobs.set_progress(
                        "Watch Chrome — Mira is recording the live platform tour…"
                    )
                result = run_parsed_action(parsed)
            else:
                # background=False runs here; jobs status already set above
                result = try_mira_command(raw, background=False)
                if result is None:
                    result = run_parsed_action(
                        {
                            "action": "video",
                            "topic": raw,
                            "aspect": "9:16",
                            "duration_sec": "20",
                            "format": "youtube_shorts",
                        }
                    )

            import re

            m = re.search(r"([A-Za-z]:\\[^\s]+\.(?:mp4|jpg|jpeg|png|webp))", result or "")
            if not m:
                m = re.search(
                    r"(data[\\/]+mira[\\/]+(?:videos|images)[\\/]+[^\s]+\.(?:mp4|jpg|jpeg|png))",
                    result or "",
                    re.I,
                )
            if m:
                media_path = m.group(1)
                cand = Path(media_path)
                if not cand.is_file():
                    from jarvis.tools.mira_jobs import ROOT

                    alt = ROOT / media_path.replace("/", "\\")
                    if alt.is_file():
                        media_path = str(alt)
                media_url = media_url_for_path(media_path)
            if not media_url:
                um = re.search(
                    r"(https?://[^\s]+/mira/media/(?:videos|images)/[^\s]+\.(?:mp4|jpg|jpeg|png|webp))",
                    result or "",
                    re.I,
                )
                if um:
                    media_url = um.group(1)
            mira_jobs.set_done(
                q,
                result or "Mira finished.",
                media_url=media_url,
                media_path=media_path,
                job_id=job_id,
            )
        except Exception as exc:
            mira_jobs.set_error(q, f"Mira failed: {str(exc)[:200]}", job_id=job_id)
            raise
        finally:
            mira_jobs.set_progress = orig  # type: ignore[assignment]

        _finish_ok("mira", task_id, result or "Mira finished.", "Ready for next brief")
    except Exception as exc:
        _finish_err("mira", task_id, exc)


def _run_hunter_task(task_id: str, raw: str) -> None:
    try:
        bus.update_task(task_id, status="running")
        _prog("hunter", task_id, "Opening Chrome — hunting keys…")

        from jarvis.tools.api_hunter import fetch_api_key
        from jarvis.tools import hunt_bus

        orig = hunt_bus.set_progress

        def bridged(message: str) -> None:
            orig(message)
            _prog("hunter", task_id, message)

        hunt_bus.set_progress = bridged  # type: ignore[assignment]
        try:
            result = fetch_api_key(raw)
        finally:
            hunt_bus.set_progress = orig  # type: ignore[assignment]

        _finish_ok("hunter", task_id, result or "Hunt finished.", "Ready to hunt keys")
    except Exception as exc:
        _finish_err("hunter", task_id, exc)


def _run_weather_task(task_id: str, raw: str) -> None:
    try:
        bus.update_task(task_id, status="running")
        _prog("weather", task_id, "Pulling forecast…")
        from jarvis.tools.web_info import get_weather

        city = ""
        lower = raw.lower()
        for prefix in ("weather in ", "forecast for ", "temperature in "):
            if prefix in lower:
                city = lower.split(prefix, 1)[1].strip().rstrip("?")
                break
        result = get_weather(city)
        _finish_ok("weather", task_id, result or "No weather data.", "Watching the skies")
    except Exception as exc:
        _finish_err("weather", task_id, exc)


def _run_mail_task(task_id: str, raw: str) -> None:
    try:
        bus.update_task(task_id, status="running")
        _prog("mail", task_id, "Checking inbox…")
        from jarvis.plugins.loader import load_plugins

        plugins = load_plugins()
        mod = plugins.get("gmail")
        result = None
        if mod and callable(getattr(mod, "handle", None)):
            result = mod.handle(raw)
        if not result:
            result = "Mail desk ready — say check inbox or send email to…"
        _finish_ok("mail", task_id, str(result), "Inbox clear")
    except Exception as exc:
        _finish_err("mail", task_id, exc)


def _run_calendar_task(task_id: str, raw: str) -> None:
    try:
        bus.update_task(task_id, status="running")
        _prog("calendar", task_id, "Opening calendar…")
        from jarvis.plugins.loader import load_plugins

        plugins = load_plugins()
        mod = plugins.get("calendar")
        result = None
        if mod and callable(getattr(mod, "handle", None)):
            result = mod.handle(raw)
        if not result:
            result = "Calendar desk ready — say what's on my calendar today."
        _finish_ok("calendar", task_id, str(result), "Schedule open")
    except Exception as exc:
        _finish_err("calendar", task_id, exc)


def _run_youtube_task(task_id: str, raw: str) -> None:
    try:
        bus.update_task(task_id, status="running")
        _prog("youtube", task_id, "Opening YouTube…")
        from jarvis.tools.command_parse import extract_youtube_query
        from jarvis.tools.system import open_youtube

        _flag, query = extract_youtube_query(raw)
        result = open_youtube(query or "")
        _finish_ok("youtube", task_id, result or "YouTube opened.", "Ready to open YouTube")
    except Exception as exc:
        _finish_err("youtube", task_id, exc)


def _run_briefing_task(task_id: str, raw: str) -> None:
    try:
        bus.update_task(task_id, status="running")
        _prog("briefing", task_id, "Building morning brief…")
        from jarvis.plugins.loader import load_plugins

        plugins = load_plugins()
        mod = plugins.get("morning_briefing")
        result = None
        if mod and callable(getattr(mod, "handle", None)):
            result = mod.handle(raw) or mod.handle("morning briefing")
        if not result:
            from jarvis.tools import system
            from jarvis.tools.web_info import get_news, get_weather

            result = " ".join(
                [
                    f"Good morning, sir. It is {system.get_time()}.",
                    system.get_system_status(),
                    get_weather(),
                    get_news(3),
                ]
            )
        _finish_ok("briefing", task_id, str(result), "Briefing stacked")
    except Exception as exc:
        _finish_err("briefing", task_id, exc)


def _run_waiter_task(task_id: str, raw: str) -> None:
    try:
        bus.update_task(task_id, status="running")
        _prog("waiter", task_id, "Tray ready — walking the floor…")
        lower = (raw or "").lower()
        if any(k in lower for k in ("lunch", "food", "hungry", "meal")):
            result = "Ravi served lunch trays to the floor, sir. Bottles and plates at the desks."
        elif any(k in lower for k in ("coffee", "tea")):
            result = "Ravi brought coffee/tea around on the tray, sir."
        elif any(k in lower for k in ("water", "bottle", "drink")):
            result = "Ravi delivered water bottles to the cabins, sir."
        else:
            result = "Ravi took the intercom order and served the floor, sir."
        _prog("waiter", task_id, "Serving…")
        _finish_ok("waiter", task_id, result, "Pantry ready")
    except Exception as exc:
        _finish_err("waiter", task_id, exc)


_RUNNERS: dict[str, Callable[[str, str], None]] = {
    "mira": _run_mira_task,
    "hunter": _run_hunter_task,
    "weather": _run_weather_task,
    "mail": _run_mail_task,
    "calendar": _run_calendar_task,
    "youtube": _run_youtube_task,
    "briefing": _run_briefing_task,
    "waiter": _run_waiter_task,
}
