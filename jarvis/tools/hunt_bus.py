"""Background API hunt status — shared via file so subprocess hunts can update UI."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STATUS_FILE = ROOT / "data" / "hunt_status.json"
_lock = threading.Lock()
# Stuck hunts (crashed worker / killed Chrome) must not block forever
STALE_SECONDS = 180


def _read() -> dict[str, Any]:
    if not STATUS_FILE.exists():
        return {"status": "idle", "response": "", "query": "", "running": False, "started_at": 0}
    try:
        data = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        return {
            "status": data.get("status", "idle"),
            "response": data.get("response", ""),
            "query": data.get("query", ""),
            "running": bool(data.get("running", False)),
            "started_at": float(data.get("started_at") or 0),
        }
    except (json.JSONDecodeError, OSError):
        return {"status": "idle", "response": "", "query": "", "running": False, "started_at": 0}


def _write(**kwargs: Any) -> None:
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = _read()
    data.update(kwargs)
    STATUS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _clear_if_stale(data: dict[str, Any]) -> dict[str, Any]:
    """Auto-unlock hunts stuck in running after STALE_SECONDS."""
    if not data.get("running"):
        return data
    started = float(data.get("started_at") or 0)
    if started and (time.time() - started) > STALE_SECONDS:
        _write(
            status="idle",
            response="Previous hunt timed out — ready again, sir.",
            query="",
            running=False,
            started_at=0,
        )
        return _read()
    # Legacy files with no started_at — clear stuck running
    if data.get("running") and not started:
        _write(status="idle", response="", query="", running=False, started_at=0)
        return _read()
    return data


def is_running() -> bool:
    with _lock:
        data = _clear_if_stale(_read())
        return bool(data.get("running", False))


def set_running(query: str) -> bool:
    with _lock:
        data = _clear_if_stale(_read())
        if data.get("running"):
            return False
        _write(
            status="running",
            response="",
            query=query,
            running=True,
            started_at=time.time(),
        )
        ok = True
    if ok:
        try:
            from jarvis.crew import bus

            bus.set_agent_status("hunter", "working", f"Hunting: {str(query or '')[:80]}")
            bus.emit(
                "chat",
                from_id="jarvis",
                to_id="hunter",
                text=f"Hunter — fetch keys for: {str(query or '')[:100]}",
            )
            bus.emit(
                "chat",
                from_id="hunter",
                to_id="jarvis",
                text="On it — Chrome opening.",
            )
        except Exception:
            pass
    return True


def set_progress(message: str) -> None:
    """Keep hunt running and update the chat-facing status (no secrets)."""
    with _lock:
        data = _read()
        if not data.get("running"):
            return
        _write(
            status="running",
            response=message,
            query=data.get("query", ""),
            running=True,
        )
    try:
        from jarvis.crew import bus

        bus.set_agent_status("hunter", "working", str(message or "")[:120])
        bus.emit(
            "progress",
            from_id="hunter",
            to_id="jarvis",
            text=str(message or "")[:200],
        )
    except Exception:
        pass


def set_done(query: str, response: str) -> None:
    with _lock:
        _write(status="done", response=response, query=query, running=False, started_at=0)
    try:
        from jarvis.crew import bus

        bus.set_agent_status("hunter", "idle", "Ready to hunt keys")
        bus.emit(
            "chat",
            from_id="hunter",
            to_id="jarvis",
            text=f"Done — {str(response or '')[:160]}",
        )
    except Exception:
        pass


def set_failed(query: str, error: str) -> None:
    with _lock:
        _write(status="error", response=error, query=query, running=False, started_at=0)
    try:
        from jarvis.crew import bus

        bus.set_agent_status("hunter", "idle", "Recovered — ready")
        bus.emit(
            "chat",
            from_id="hunter",
            to_id="jarvis",
            text=f"Snag — {str(error or '')[:140]}",
        )
    except Exception:
        pass


def get_status() -> dict[str, Any]:
    with _lock:
        data = _clear_if_stale(_read())
        return {"status": data["status"], "response": data["response"], "query": data["query"]}


def force_reset() -> None:
    with _lock:
        _write(status="idle", response="", query="", running=False, started_at=0)


def clear_if_done() -> dict[str, Any]:
    with _lock:
        out = get_status()
        data = _read()
        if data["status"] in ("done", "error"):
            _write(status="idle", response="", query="", running=False)
        return out
