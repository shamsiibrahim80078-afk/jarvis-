"""Clip library — bank vertical Shorts for later schedule / export."""

from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
LIB_DIR = ROOT / "data" / "mira" / "clip_library"
INDEX = LIB_DIR / "index.json"


def _load() -> dict[str, Any]:
    LIB_DIR.mkdir(parents=True, exist_ok=True)
    if not INDEX.is_file():
        return {"clips": []}
    try:
        data = json.loads(INDEX.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"clips": []}
    except Exception:
        return {"clips": []}


def _save(data: dict[str, Any]) -> None:
    LIB_DIR.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps(data, indent=2), encoding="utf-8")


def add_clip(path: str | Path, *, topic: str = "", tags: list[str] | None = None) -> dict[str, Any]:
    src = Path(path)
    if not src.is_file():
        return {"ok": False, "message": "Clip file missing"}
    LIB_DIR.mkdir(parents=True, exist_ok=True)
    dest = LIB_DIR / f"{int(time.time())}_{src.name}"
    try:
        shutil.copy2(src, dest)
    except Exception as exc:
        return {"ok": False, "message": str(exc)[:160]}
    data = _load()
    entry = {
        "path": str(dest),
        "topic": (topic or "")[:120],
        "tags": tags or [],
        "added_at": time.time(),
        "used": False,
    }
    clips = list(data.get("clips") or [])
    clips.append(entry)
    data["clips"] = clips[-200:]
    _save(data)
    return {"ok": True, "path": str(dest), "message": f"Saved to clip library: {dest.name}"}


def list_clips(limit: int = 20) -> list[dict[str, Any]]:
    clips = list(_load().get("clips") or [])
    return list(reversed(clips[-max(1, min(50, int(limit))):]))


def _topic_tokens(text: str) -> set[str]:
    stop = {
        "a", "an", "the", "and", "or", "of", "to", "for", "in", "on", "with",
        "video", "short", "shorts", "clip", "about", "make", "create",
    }
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 2 and w not in stop}


def next_unused(*, mark_used: bool = True, topic: str = "") -> dict[str, Any] | None:
    """Return next unused clip. If topic given, prefer topic-matched clips only."""
    data = _load()
    clips = list(data.get("clips") or [])
    want = _topic_tokens(topic) if topic else set()

    def _ok(c: dict[str, Any]) -> bool:
        if c.get("used"):
            return False
        p = Path(str(c.get("path") or ""))
        if not p.is_file():
            return False
        if not want:
            return True
        clip_toks = _topic_tokens(str(c.get("topic") or "")) | {
            str(t).lower() for t in (c.get("tags") or []) if str(t).strip()
        }
        if not clip_toks:
            return False
        return bool(want & clip_toks)

    for c in clips:
        if not _ok(c):
            continue
        if mark_used:
            c["used"] = True
            data["clips"] = clips
            _save(data)
        return c
    # No topic match → do not post unrelated library clip
    if want:
        return None
    return None


def status_message() -> str:
    clips = list(_load().get("clips") or [])
    unused = sum(1 for c in clips if not c.get("used") and Path(str(c.get("path") or "")).is_file())
    return f"Clip library: {len(clips)} total, {unused} unused ready to post."
