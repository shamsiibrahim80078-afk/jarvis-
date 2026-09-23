"""Crew live bus — tasks, agent status, inter-agent chat (file + in-memory)."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = ROOT / "data" / "crew" / "state.json"
EVENTS_PATH = ROOT / "data" / "crew" / "events.jsonl"

_lock = threading.RLock()
_listeners: list[Callable[[dict[str, Any]], None]] = []
_seq = 0


def add_listener(cb: Callable[[dict[str, Any]], None]) -> None:
    with _lock:
        _listeners.append(cb)


def _notify(event: dict[str, Any]) -> None:
    for cb in list(_listeners):
        try:
            cb(event)
        except Exception:
            pass


def _default_state() -> dict[str, Any]:
    from jarvis.crew.registry import list_agents

    agents = {a["id"]: a for a in list_agents()}
    return {
        "agents": agents,
        "tasks": [],
        "chat": [],
        "updated_at": time.time(),
    }


def _load() -> dict[str, Any]:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not STATE_PATH.is_file():
        return _default_state()
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return _default_state()
        base = _default_state()
        # Merge agent defs (keep live status/activity)
        for aid, agent in base["agents"].items():
            live = (data.get("agents") or {}).get(aid) or {}
            agent["status"] = live.get("status") or agent["status"]
            agent["activity"] = live.get("activity") or agent["activity"]
            agent["task_id"] = live.get("task_id")
        data["agents"] = base["agents"]
        data.setdefault("tasks", [])
        data.setdefault("chat", [])
        return data
    except Exception:
        return _default_state()


def _save(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = time.time()
    payload = json.dumps(state, indent=2)
    # Unique tmp avoids Windows lock races when two writers collide on state.tmp
    tmp = STATE_PATH.parent / f"state.{uuid.uuid4().hex[:8]}.tmp"
    last_err: Exception | None = None
    for attempt in range(10):
        try:
            tmp.write_text(payload, encoding="utf-8")
            try:
                os.replace(tmp, STATE_PATH)
            except PermissionError:
                STATE_PATH.write_text(payload, encoding="utf-8")
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass
            return
        except Exception as exc:
            last_err = exc
            time.sleep(0.03 * (attempt + 1))
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            tmp = STATE_PATH.parent / f"state.{uuid.uuid4().hex[:8]}.tmp"
    # Soft-fail: keep process alive; in-memory listeners already have the event
    if last_err:
        import logging
        logging.getLogger(__name__).warning("crew state save failed: %s", last_err)


def _append_event(event: dict[str, Any]) -> None:
    EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with EVENTS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def get_state() -> dict[str, Any]:
    with _lock:
        return _load()


def emit(
    kind: str,
    *,
    from_id: str = "jarvis",
    to_id: str | None = None,
    text: str = "",
    task_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    global _seq
    with _lock:
        _seq += 1
        event = {
            "id": f"e_{_seq}_{uuid.uuid4().hex[:6]}",
            "seq": _seq,
            "kind": kind,  # chat | status | task | progress | system
            "from": from_id,
            "to": to_id,
            "text": text,
            "task_id": task_id,
            "ts": time.time(),
            **(extra or {}),
        }
        st = _load()
        if kind in ("chat", "system", "progress") and text:
            chat = list(st.get("chat") or [])
            chat.append(event)
            st["chat"] = chat[-200:]
        _save(st)
        _append_event(event)
    _notify(event)
    return event


def set_agent_status(agent_id: str, status: str, activity: str, *, task_id: str | None = None) -> None:
    with _lock:
        st = _load()
        agents = st.get("agents") or {}
        if agent_id not in agents:
            return
        agents[agent_id]["status"] = status
        agents[agent_id]["activity"] = activity
        if task_id is not None:
            agents[agent_id]["task_id"] = task_id
        elif status in ("idle", "online"):
            agents[agent_id]["task_id"] = None
        st["agents"] = agents
        _save(st)
    emit(
        "status",
        from_id=agent_id,
        text=activity,
        task_id=task_id,
        extra={"status": status, "activity": activity},
    )


def create_task(
    title: str,
    *,
    agent_id: str,
    owner_text: str = "",
) -> dict[str, Any]:
    with _lock:
        st = _load()
        task = {
            "id": f"t_{uuid.uuid4().hex[:10]}",
            "title": title[:160],
            "agent_id": agent_id,
            "owner_text": owner_text[:400],
            "status": "queued",
            "created_at": time.time(),
            "updated_at": time.time(),
            "result": "",
        }
        tasks = list(st.get("tasks") or [])
        tasks.append(task)
        st["tasks"] = tasks[-80:]
        _save(st)
    emit(
        "task",
        from_id="jarvis",
        to_id=agent_id,
        text=f"Assigned: {title}",
        task_id=task["id"],
        extra={"task": task},
    )
    return task


def update_task(task_id: str, *, status: str | None = None, result: str | None = None) -> None:
    with _lock:
        st = _load()
        tasks = list(st.get("tasks") or [])
        for t in tasks:
            if t.get("id") == task_id:
                if status:
                    t["status"] = status
                if result is not None:
                    t["result"] = result[:800]
                t["updated_at"] = time.time()
                break
        st["tasks"] = tasks
        _save(st)
    emit(
        "task",
        from_id="jarvis",
        text=f"Task {task_id} → {status or 'updated'}",
        task_id=task_id,
        extra={"status": status, "result": (result or "")[:200]},
    )


def events_since(seq: int = 0, limit: int = 80) -> list[dict[str, Any]]:
    if not EVENTS_PATH.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        lines = EVENTS_PATH.read_text(encoding="utf-8").splitlines()
        for line in lines[-(limit * 3) :]:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if int(ev.get("seq") or 0) > int(seq or 0):
                out.append(ev)
        return out[-limit:]
    except Exception:
        return []
