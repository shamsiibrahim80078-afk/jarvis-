"""Growth schedule — auto-post Shorts every N hours (Vugola cadence).

Persists topics + next run in data/mira/growth_schedule.json.
Background thread ticks while Jarvis server is up.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = ROOT / "data" / "mira" / "growth_schedule.json"

_lock = threading.RLock()
_stop = threading.Event()
_thread: threading.Thread | None = None

DEFAULT_INTERVAL_HOURS = 3.5
MIN_INTERVAL_HOURS = 2.0
MAX_INTERVAL_HOURS = 12.0


def _default_state() -> dict[str, Any]:
    return {
        "enabled": False,
        "interval_hours": DEFAULT_INTERVAL_HOURS,
        "topics": [],
        "next_index": 0,
        "last_post_at": 0.0,
        "next_post_at": 0.0,
        "last_result": "",
        "last_url": "",
        "posts_done": 0,
        "daily_cap": 5,
        "posts_today": 0,
        "posts_day": "",
        "recent_topics": [],  # [{topic, at}]
        "peak_hours": [12, 18, 20, 21],
        "use_peak_hours": True,
    }


def _local_day() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())


def _normalize_day_counters(st: dict[str, Any]) -> None:
    day = _local_day()
    if str(st.get("posts_day") or "") != day:
        st["posts_day"] = day
        st["posts_today"] = 0


def _topic_key(topic: str) -> str:
    return re.sub(r"\s+", " ", (topic or "").strip().lower())


def _is_duplicate(st: dict[str, Any], topic: str, *, within_hours: float = 48.0) -> bool:
    key = _topic_key(topic)
    if not key:
        return False
    cutoff = time.time() - within_hours * 3600
    recent = list(st.get("recent_topics") or [])
    for r in recent:
        if not isinstance(r, dict):
            continue
        if float(r.get("at") or 0) < cutoff:
            continue
        if _topic_key(str(r.get("topic") or "")) == key:
            return True
    return False


def _mark_posted(st: dict[str, Any], topic: str) -> None:
    _normalize_day_counters(st)
    st["posts_today"] = int(st.get("posts_today") or 0) + 1
    recent = [r for r in (st.get("recent_topics") or []) if isinstance(r, dict)]
    recent.append({"topic": topic, "at": time.time()})
    st["recent_topics"] = recent[-60:]


def next_slot_after(
    from_ts: float | None = None,
    *,
    interval_hours: float = DEFAULT_INTERVAL_HOURS,
    peak_hours: list[int] | None = None,
    use_peak: bool = True,
) -> float:
    """Next post time — prefer evening/peak hours, else interval."""
    now = float(from_ts if from_ts is not None else time.time())
    min_gap = max(MIN_INTERVAL_HOURS, float(interval_hours or DEFAULT_INTERVAL_HOURS)) * 3600
    earliest = now + min_gap * 0.85
    if not use_peak:
        return now + min_gap

    peaks = peak_hours or [12, 18, 20, 21]
    peaks = sorted({int(h) % 24 for h in peaks})
    # Search next 3 days for a peak hour after earliest
    lt = time.localtime(earliest)
    for day_add in range(0, 4):
        for h in peaks:
            cand_struct = (
                lt.tm_year,
                lt.tm_mon,
                lt.tm_mday + day_add,
                h,
                0,
                0,
                0,
                0,
                -1,
            )
            try:
                cand = time.mktime(cand_struct)
            except Exception:
                continue
            if cand >= earliest:
                return cand
    return now + min_gap


def status_message() -> str:
    st = get_status()
    if not st.get("enabled"):
        topics = st.get("topics") or []
        tip = f" Topics queued: {', '.join(topics[:5])}." if topics else ""
        return f"Shorts schedule is OFF, sir.{tip} Say: schedule shorts about coffee, dogs every 3 hours"
    topics = st.get("topics") or []
    mins = st.get("minutes_until_next")
    nxt = f" Next in ~{mins} min." if mins is not None else ""
    last = st.get("last_url") or st.get("last_result") or ""
    last_s = f" Last: {last}" if last else ""
    cap = int(st.get("daily_cap") or 5)
    today = int(st.get("posts_today") or 0)
    peak = "peak-hours ON" if st.get("use_peak_hours", True) else "flat interval"
    return (
        f"Schedule ON — every {st.get('interval_hours')}h ({peak}), "
        f"{len(topics)} topics, today {today}/{cap}, total {st.get('posts_done', 0)}."
        f"{nxt}{last_s}"
    )


def start_schedule(
    topics: list[str],
    *,
    interval_hours: float = DEFAULT_INTERVAL_HOURS,
    post_now: bool = False,
) -> str:
    topics = [re.sub(r"\s+", " ", t).strip() for t in topics if str(t).strip()]
    topics = [t for t in topics if t][:40]
    if not topics:
        return "Need at least one topic, sir. Example: schedule shorts about coffee, dogs every 3 hours"
    hours = max(MIN_INTERVAL_HOURS, min(MAX_INTERVAL_HOURS, float(interval_hours or DEFAULT_INTERVAL_HOURS)))
    now = time.time()
    with _lock:
        st = _load()
        st["enabled"] = True
        st["topics"] = topics
        st["interval_hours"] = hours
        st["next_index"] = 0
        st.setdefault("daily_cap", 5)
        st.setdefault("peak_hours", [12, 18, 20, 21])
        st.setdefault("use_peak_hours", True)
        st["next_post_at"] = (
            now
            if post_now
            else next_slot_after(
                now,
                interval_hours=hours,
                peak_hours=list(st.get("peak_hours") or [12, 18, 20, 21]),
                use_peak=bool(st.get("use_peak_hours", True)),
            )
        )
        _save(st)
    ensure_worker()
    when = "first post starting soon" if post_now else f"first post ~peak slot"
    return (
        f"Schedule ON, sir — {len(topics)} topics every {hours}h with peak hours ({when}). "
        f"Daily cap {st.get('daily_cap', 5)}. Queue: {', '.join(topics[:6])}"
        f"{'…' if len(topics) > 6 else ''}. Say 'schedule status' or 'stop schedule'."
    )


def _load() -> dict[str, Any]:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not STATE_PATH.is_file():
        return _default_state()
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return _default_state()
        out = _default_state()
        out.update(data)
        topics = out.get("topics") or []
        if not isinstance(topics, list):
            topics = []
        out["topics"] = [str(t).strip() for t in topics if str(t).strip()][:40]
        try:
            out["interval_hours"] = float(out.get("interval_hours") or DEFAULT_INTERVAL_HOURS)
        except (TypeError, ValueError):
            out["interval_hours"] = DEFAULT_INTERVAL_HOURS
        out["interval_hours"] = max(MIN_INTERVAL_HOURS, min(MAX_INTERVAL_HOURS, out["interval_hours"]))
        out["enabled"] = bool(out.get("enabled"))
        return out
    except Exception:
        return _default_state()


def _save(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def get_status() -> dict[str, Any]:
    with _lock:
        st = _load()
        _normalize_day_counters(st)
    now = time.time()
    nxt = float(st.get("next_post_at") or 0)
    mins = max(0, int((nxt - now) / 60)) if st.get("enabled") and nxt else None
    return {
        **st,
        "minutes_until_next": mins,
        "worker_alive": bool(_thread and _thread.is_alive()),
    }


def add_topics(topics: list[str]) -> str:
    add = [re.sub(r"\s+", " ", t).strip() for t in topics if str(t).strip()]
    add = [t for t in add if t]
    if not add:
        return "No topics to add, sir."
    with _lock:
        st = _load()
        cur = list(st.get("topics") or [])
        for t in add:
            if t.lower() not in {x.lower() for x in cur}:
                cur.append(t)
        st["topics"] = cur[:40]
        if not st.get("enabled"):
            st["enabled"] = True
            st["next_post_at"] = time.time() + float(st.get("interval_hours") or DEFAULT_INTERVAL_HOURS) * 3600
        _save(st)
    ensure_worker()
    return f"Added {len(add)} topic(s). Queue now has {len(get_status().get('topics') or [])}."


def stop_schedule() -> str:
    with _lock:
        st = _load()
        st["enabled"] = False
        st["next_post_at"] = 0.0
        _save(st)
    return "Shorts schedule stopped, sir."


def _pick_topic(st: dict[str, Any]) -> str | None:
    topics = list(st.get("topics") or [])
    if not topics:
        return None
    n = len(topics)
    start = int(st.get("next_index") or 0) % n
    for offset in range(n):
        i = (start + offset) % n
        topic = topics[i]
        if _is_duplicate(st, topic):
            continue
        st["next_index"] = (i + 1) % n
        return topic
    # All recent dups — still advance
    topic = topics[start]
    st["next_index"] = (start + 1) % n
    return topic


def run_due_post(*, progress_cb: Callable[[str], None] | None = None) -> dict[str, Any]:
    """If schedule is due, generate + publish one Short. Safe to call often."""
    with _lock:
        st = _load()
        if not st.get("enabled"):
            return {"ok": False, "skipped": True, "reason": "disabled"}
        topics = st.get("topics") or []
        if not topics:
            return {"ok": False, "skipped": True, "reason": "no_topics"}
        now = time.time()
        nxt = float(st.get("next_post_at") or 0)
        if nxt and now < nxt - 1:
            return {"ok": False, "skipped": True, "reason": "not_due", "next_post_at": nxt}

        _normalize_day_counters(st)
        cap = int(st.get("daily_cap") or 5)
        if int(st.get("posts_today") or 0) >= cap:
            # Push to tomorrow first peak
            st["next_post_at"] = next_slot_after(
                now + 3600,
                interval_hours=float(st.get("interval_hours") or DEFAULT_INTERVAL_HOURS),
                peak_hours=list(st.get("peak_hours") or [12, 18, 20, 21]),
                use_peak=True,
            )
            _save(st)
            return {"ok": False, "skipped": True, "reason": "daily_cap", "daily_cap": cap}

        # Prefer unused clip from library occasionally
        topic = _pick_topic(st)
        # Do NOT advance next_post_at until the post attempt finishes —
        # otherwise a failed generate locks out the queue for hours.
        st["last_post_at"] = now
        _save(st)

    if not topic:
        return {"ok": False, "message": "No topic"}

    def _p(m: str) -> None:
        if progress_cb:
            try:
                progress_cb(m)
            except Exception:
                pass
        logger.info("schedule: %s", m)

    # Try library clip first — only if it matches THIS schedule topic
    lib_clip = None
    try:
        from jarvis.mira.clip_library import next_unused

        lib_clip = next_unused(mark_used=True, topic=topic)
    except Exception:
        lib_clip = None

    _p(f"Scheduled Short: {topic}" + (" (from clip library)" if lib_clip else ""))
    try:
        if lib_clip and lib_clip.get("path"):
            from jarvis.mira.youtube_upload import upload_video
            from jarvis.mira.packaging import pack_short
            from jarvis.mira.ab_titles import pick_ab_title

            pack = pack_short(str(lib_clip.get("topic") or topic))
            title, _, _ = pick_ab_title(str(lib_clip.get("topic") or topic), pack)
            out = upload_video(
                path=str(lib_clip["path"]),
                title=title,
                description=str(pack.get("description") or ""),
                tags=list(pack.get("tags") or []),
                privacy="public",
                force_shorts=True,
                progress_cb=progress_cb,
            )
            if out.get("ok"):
                out["message"] = out.get("message") or f"Library clip live: {out.get('url')}"
        else:
            from jarvis.mira.growth import run_growth_short

            out = run_growth_short(topic, progress_cb=progress_cb)
    except Exception as exc:
        out = {"ok": False, "message": str(exc)[:200]}

    with _lock:
        st = _load()
        st["last_result"] = str(out.get("message") or "")[:400]
        st["last_url"] = str(out.get("url") or "")
        hours = float(st.get("interval_hours") or DEFAULT_INTERVAL_HOURS)
        if out.get("ok"):
            st["posts_done"] = int(st.get("posts_done") or 0) + 1
            _mark_posted(st, topic)
            st["next_post_at"] = next_slot_after(
                time.time(),
                interval_hours=hours,
                peak_hours=list(st.get("peak_hours") or [12, 18, 20, 21]),
                use_peak=bool(st.get("use_peak_hours", True)),
            )
        else:
            # Retry sooner on failure (15–30 min), don't wait for next peak
            st["next_post_at"] = time.time() + 15 * 60
        _save(st)

    return out


def _worker_loop() -> None:
    logger.info("Growth schedule worker started")
    while not _stop.is_set():
        try:
            # Never steal CPU/GPU while the user has a Mira generate running
            try:
                from jarvis.tools.mira_jobs import is_running as mira_busy

                if mira_busy():
                    _stop.wait(20.0)
                    continue
            except Exception:
                pass
            st = get_status()
            if st.get("enabled") and st.get("topics"):
                nxt = float(st.get("next_post_at") or 0)
                now = time.time()
                if not nxt or now >= nxt:
                    run_due_post()
        except Exception as exc:
            logger.warning("schedule tick failed: %s", exc)
        # Wake often enough for 3–4h cadence without busy-loop
        _stop.wait(45.0)
    logger.info("Growth schedule worker stopped")


def force_due_now() -> None:
    """Mark schedule as due immediately (for 'post first now')."""
    with _lock:
        st = _load()
        st["enabled"] = True
        st["next_post_at"] = time.time() - 1
        _save(st)
    ensure_worker()


def ensure_worker() -> None:
    global _thread
    with _lock:
        if _thread and _thread.is_alive():
            return
        _stop.clear()
        _thread = threading.Thread(target=_worker_loop, daemon=True, name="mira-schedule")
        _thread.start()


def shutdown_worker() -> None:
    _stop.set()


# ── Natural language ───────────────────────────────────────────

def is_schedule_intent(text: str) -> bool:
    t = (text or "").lower()
    if not t:
        return False
    if re.search(r"\b(stop|pause|cancel)\s+(?:the\s+)?(?:shorts?\s+)?schedule\b", t):
        return True
    if re.search(r"\b(schedule\s+status|status\s+of\s+(?:the\s+)?schedule)\b", t):
        return True
    if re.search(
        r"\b(schedule|auto[\s-]?post|auto[\s-]?upload)\b.{0,40}\b(short|shorts|reel|viral|growth)\b",
        t,
    ):
        return True
    if re.search(r"\bschedule\s+shorts?\b", t):
        return True
    if re.search(r"\badd\s+(?:schedule\s+)?topics?\b", t):
        return True
    return False


def parse_schedule_command(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    lower = raw.lower()
    if not lower:
        return None

    if re.search(r"\b(stop|pause|cancel)\s+(?:the\s+)?(?:shorts?\s+)?schedule\b", lower):
        return {"action": "schedule_stop"}

    if re.search(r"\b(schedule\s+status|status\s+of\s+(?:the\s+)?schedule|is\s+schedule\s+on)\b", lower):
        return {"action": "schedule_status"}

    # Interval
    hours = DEFAULT_INTERVAL_HOURS
    hm = re.search(r"every\s+(\d+(?:\.\d+)?)\s*h(?:ours?)?", lower)
    if hm:
        try:
            hours = float(hm.group(1))
        except ValueError:
            hours = DEFAULT_INTERVAL_HOURS
    else:
        hm = re.search(r"every\s+(\d+)\s*(?:min|minutes)", lower)
        if hm:
            hours = max(MIN_INTERVAL_HOURS, float(hm.group(1)) / 60.0)

    post_now = bool(re.search(r"\b(now|right\s+away|immediately|post\s+first\s+now)\b", lower))

    # add topics …
    if re.search(r"\badd\s+(?:schedule\s+)?topics?\b", lower):
        body = re.sub(r"(?i)^.*?\badd\s+(?:schedule\s+)?topics?\s*(?:about|:)?\s*", "", raw).strip()
        topics = _split_topics(body)
        return {"action": "schedule_add", "topics": topics}

    if not is_schedule_intent(raw):
        return None

    # schedule shorts about A, B, C every 3 hours
    body = raw
    body = re.sub(
        r"(?i)\b(schedule|auto[\s-]?post|auto[\s-]?upload)\s+"
        r"(?:viral\s+|growth\s+)?(?:shorts?|reels?|videos?)?\s*"
        r"(?:about|on|for|:)?\s*",
        "",
        body,
        count=1,
    )
    body = re.sub(r"(?i)\bevery\s+\d+(?:\.\d+)?\s*(?:h(?:ours?)?|min(?:utes)?)\b", " ", body)
    body = re.sub(r"(?i)\b(now|right\s+away|immediately|post\s+first\s+now|and\s+upload|public)\b", " ", body)
    topics = _split_topics(body)
    if not topics:
        # maybe "schedule shorts every 3 hours" with existing queue
        st = get_status()
        if st.get("topics"):
            return {
                "action": "schedule_start",
                "topics": list(st["topics"]),
                "interval_hours": hours,
                "post_now": post_now,
            }
        return {
            "action": "schedule_status",
            "_hint": "Need topics. Example: schedule shorts about coffee, dogs, sunset every 3 hours",
        }

    return {
        "action": "schedule_start",
        "topics": topics,
        "interval_hours": hours,
        "post_now": post_now,
    }


def _split_topics(body: str) -> list[str]:
    t = re.sub(r"\s+", " ", (body or "").strip())
    if not t:
        return []
    # Prefer commas / "and"
    parts = re.split(r"\s*,\s*|\s+and\s+", t, flags=re.I)
    out: list[str] = []
    for p in parts:
        p = re.sub(r"^(?:about|on|for)\s+", "", p.strip(), flags=re.I)
        p = p.strip(" .,:;-")
        if len(p) >= 2:
            out.append(p[:120])
    # If no split worked and string is short, one topic
    if not out and len(t) >= 2:
        out = [t[:120]]
    return out[:40]
