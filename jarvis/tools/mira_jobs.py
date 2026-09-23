"""Background Mira generate jobs — same pattern as hunt_bus (poll until done)."""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STATUS_FILE = ROOT / "data" / "mira_status.json"
_lock = threading.Lock()
# Full platform tours (20+ live pages) can run 45–90 min — don't fake-timeout mid-record
STALE_SECONDS = 7200


def _empty() -> dict[str, Any]:
    return {
        "status": "idle",
        "response": "",
        "query": "",
        "running": False,
        "started_at": 0,
        "media_url": None,
        "media_path": None,
        "job_id": "",
        "platform": "",
    }


def _read() -> dict[str, Any]:
    if not STATUS_FILE.exists():
        return _empty()
    try:
        data = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        base = _empty()
        base.update(
            {
                "status": data.get("status", "idle"),
                "response": data.get("response", ""),
                "query": data.get("query", ""),
                "running": bool(data.get("running", False)),
                "started_at": float(data.get("started_at") or 0),
                "media_url": data.get("media_url"),
                "media_path": data.get("media_path"),
                "job_id": str(data.get("job_id") or ""),
                "platform": str(data.get("platform") or ""),
            }
        )
        return base
    except (json.JSONDecodeError, OSError):
        return _empty()


def _write(**kwargs: Any) -> None:
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = _read()
    data.update(kwargs)
    STATUS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _clear_if_stale(data: dict[str, Any]) -> dict[str, Any]:
    if not data.get("running"):
        return data
    started = float(data.get("started_at") or 0)
    if started and (time.time() - started) > STALE_SECONDS:
        _write(
            status="error",
            response="Previous Mira job timed out — ready again, sir.",
            query="",
            running=False,
            started_at=0,
            job_id="",
            platform="",
        )
        return _read()
    if data.get("running") and not started:
        _write(status="idle", response="", query="", running=False, started_at=0, job_id="", platform="")
        return _read()
    return data


def is_running() -> bool:
    with _lock:
        return bool(_clear_if_stale(_read()).get("running"))


def set_running(query: str, *, platform: str = "") -> str | None:
    """Start a job. Returns job_id, or None if another job is already running."""
    job_id = uuid.uuid4().hex[:12]
    with _lock:
        data = _clear_if_stale(_read())
        if data.get("running"):
            return None
        _write(
            status="running",
            response="Generating with Mira…",
            query=query,
            running=True,
            started_at=time.time(),
            media_url=None,
            media_path=None,
            job_id=job_id,
            platform=str(platform or ""),
        )
    try:
        from jarvis.crew import bus

        bus.set_agent_status("mira", "working", f"Studio: {str(query or '')[:80]}")
        bus.emit(
            "chat",
            from_id="jarvis",
            to_id="mira",
            text=f"Mira — {str(query or '')[:120]}",
        )
    except Exception:
        pass
    return job_id


def set_progress(message: str, *, job_id: str | None = None) -> None:
    """Update running job progress. Ignores stale workers from a previous job_id."""
    with _lock:
        data = _read()
        if not data.get("running"):
            return
        current = str(data.get("job_id") or "")
        if job_id and current and job_id != current:
            return  # zombie worker from an older job — do not overwrite
        _write(
            status="running",
            response=str(message or "")[:240],
            query=data.get("query", ""),
            running=True,
            job_id=current or job_id or "",
            platform=data.get("platform", ""),
        )
    try:
        from jarvis.crew import bus

        bus.set_agent_status("mira", "working", str(message or "")[:120])
        bus.emit(
            "progress",
            from_id="mira",
            to_id="jarvis",
            text=str(message or "")[:200],
        )
    except Exception:
        pass
    try:
        qpath = ROOT / "data" / "speak_queue.jsonl"
        qpath.parent.mkdir(parents=True, exist_ok=True)
        line = str(message or "").strip()[:160]
        if line:
            with qpath.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"text": line, "ts": time.time()}) + "\n")
    except Exception:
        pass


def set_done(
    query: str,
    response: str,
    *,
    media_url: str | None = None,
    media_path: str | None = None,
    job_id: str | None = None,
) -> None:
    with _lock:
        data = _read()
        current = str(data.get("job_id") or "")
        if job_id and current and job_id != current:
            return
        _write(
            status="done",
            response=response,
            query=query,
            running=False,
            started_at=0,
            media_url=media_url,
            media_path=media_path,
            job_id="",
            platform="",
        )
    try:
        from jarvis.crew import bus

        bus.set_agent_status("mira", "idle", "Ready for next brief")
        bus.emit("chat", from_id="mira", to_id="jarvis", text=f"Done — {str(response or '')[:160]}")
    except Exception:
        pass


def set_error(query: str, response: str, *, job_id: str | None = None) -> None:
    with _lock:
        data = _read()
        current = str(data.get("job_id") or "")
        if job_id and current and job_id != current:
            return
        _write(
            status="error",
            response=response,
            query=query,
            running=False,
            started_at=0,
            media_url=None,
            media_path=None,
            job_id="",
            platform="",
        )


def get_status() -> dict[str, Any]:
    with _lock:
        return _clear_if_stale(_read())


def start_job(parsed: dict[str, Any], raw: str) -> str:
    """Kick off background Mira/YouTube job; return immediate ack for the HUD."""
    from jarvis.tools.mira_tool import (
        media_url_for_path,
        run_parsed_action,
    )

    action = str(parsed.get("action") or "")
    q = (parsed.get("topic") or raw or "mira")[:200]
    plat_id = ""
    try:
        from jarvis.mira.platforms import detect_platform

        plat = detect_platform(raw) or detect_platform(q)
        if plat:
            plat_id = str(plat.get("id") or "")
    except Exception:
        pass

    # New explicit ask cancels leftover format menus from a previous topic
    try:
        from jarvis.mira.session import clear_pending

        if parsed.get("action") in ("video", "image") and (plat_id or parsed.get("platform_tour")):
            clear_pending()
    except Exception:
        pass

    try:
        from jarvis.crew import bus

        bus.emit("chat", from_id="owner", to_id="jarvis", text=raw[:200])
        bus.emit(
            "chat",
            from_id="jarvis",
            to_id="mira",
            text=f"Mira — job from main floor: {raw[:140]}",
        )
        bus.set_agent_status("mira", "working", f"Job: {raw[:80]}")
        bus.create_task(raw[:120], agent_id="mira", owner_text=raw)
    except Exception:
        pass

    job_id = set_running(q, platform=plat_id)
    if not job_id:
        busy = get_status()
        busy_q = str(busy.get("query") or "another job")[:80]
        busy_p = str(busy.get("platform") or "")
        extra = f" ({busy_p})" if busy_p else ""
        return f"Mira is already busy on{extra} {busy_q}, sir. Wait for it to finish."

    def _worker() -> None:
        # Bind progress to THIS job so a zombie previous worker cannot overwrite HUD
        jid = job_id

        try:
            import jarvis.tools.mira_jobs as jobs_mod

            orig_progress = jobs_mod.set_progress

            def _prog_bound(msg: str, *, job_id: str | None = None, **_kwargs: object) -> None:
                # Call the REAL set_progress (orig), never the patched name (recursion)
                orig_progress(msg, job_id=str(job_id or jid))

            jobs_mod.set_progress = _prog_bound  # type: ignore[assignment]
            try:
                if action == "youtube_upload":
                    _prog_bound("Uploading last video to YouTube…")
                elif action.startswith("edit") or action in ("crop", "trim", "mute", "speed", "volume", "text"):
                    _prog_bound("Editing your video…")
                elif parsed.get("use_uploads") or parsed.get("media_paths"):
                    _prog_bound("Using your uploads + building video…")
                else:
                    try:
                        from jarvis.mira.platforms import detect_platform, wants_platform_record

                        ask = str(parsed.get("topic") or raw or "")
                        plat = detect_platform(ask) or detect_platform(raw)
                        if plat and wants_platform_record(ask or raw):
                            _prog_bound(
                                f"Watch Chrome — Mira is recording live {plat['name']} (not stock)…"
                            )
                        else:
                            _prog_bound("Directing shots and assembling HD video…")
                    except Exception:
                        _prog_bound("Directing shots and assembling HD video…")
                result = run_parsed_action(parsed)
            finally:
                jobs_mod.set_progress = orig_progress  # type: ignore[assignment]

            media_path = None
            media_url = None
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
                if not Path(media_path).is_file():
                    cand = ROOT / media_path.replace("/", "\\")
                    if cand.is_file():
                        media_path = str(cand)
                media_url = media_url_for_path(media_path)
            if not media_url:
                um = re.search(
                    r"(https?://[^\s]+/mira/media/(?:videos|images)/[^\s]+\.(?:mp4|jpg|jpeg|png|webp))",
                    result or "",
                    re.I,
                )
                if um:
                    media_url = um.group(1)
                    if not media_path:
                        leaf = Path(um.group(1)).name
                        for sub in ("videos", "images"):
                            cand = ROOT / "data" / "mira" / sub / leaf
                            if cand.is_file():
                                media_path = str(cand)
                                break
            if not media_path:
                fm = re.search(
                    r"\b((?:edit_)?[A-Za-z0-9_\-]+\.(?:mp4|jpg|jpeg|png|webp))\b",
                    result or "",
                    re.I,
                )
                if fm:
                    leaf = fm.group(1)
                    for sub in ("videos", "images"):
                        cand = ROOT / "data" / "mira" / sub / leaf
                        if cand.is_file():
                            media_path = str(cand)
                            media_url = media_url or media_url_for_path(media_path)
                            break
            if action == "youtube_upload":
                ym = re.search(r"(https?://(?:youtu\.be/|www\.youtube\.com/watch\?v=)[\w-]+)", result or "")
                if ym:
                    media_url = ym.group(1)
            set_done(q, result, media_url=media_url, media_path=media_path, job_id=job_id)
        except Exception as exc:
            set_error(q, f"Mira failed: {str(exc)[:200]}", job_id=job_id)

    threading.Thread(target=_worker, daemon=True, name=f"mira-job-{job_id}").start()
    if action == "growth_post":
        return (
            "Growth mode on, sir — making a viral Short, burning the hook, "
            "then publishing PUBLIC for views + subs. Watch Chrome + chat %."
        )
    if action == "clip_shorts":
        up = " then upload each PUBLIC" if parsed.get("upload") else ""
        return (
            f"Clipping mode on, sir — cutting last video into vertical Shorts"
            f"{up}. Watch chat %."
        )
    if action == "schedule_post_now":
        return (
            "Schedule firing now, sir — making the next Short with AI title/hook "
            "then publishing PUBLIC. Watch Chrome + chat %."
        )
    if action == "youtube_upload":
        priv = str(parsed.get("privacy") or "public")
        return (
            f"Publishing Short to YouTube ({priv}), sir. "
            "Watch Chrome Studio + chat % — auto title/desc — Done when live."
        )
    if action == "youtube_upload_ask":
        return "Opening YouTube Upload in Chrome, sir."
    if action == "image":
        return "Generating your image now, sir — usually under a minute. I'll open it in Chrome when ready."
    if action in ("youtube_connect", "youtube_status"):
        return "Working on YouTube auth, sir."
    if (plat_id):
        return (
            f"Generating your live {plat_id} screen-tour video now, sir — "
            "watch progress (can take several minutes). "
            "I'll open it in a new Chrome tab when ready."
        )
    return (
        "Generating your video now, sir — about one to two minutes. "
        "I'll open it in a new Chrome tab when ready."
    )
