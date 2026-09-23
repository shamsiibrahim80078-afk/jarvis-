"""Pending Mira brief — wait for format/mood before generating."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PENDING_FILE = ROOT / "data" / "mira" / "pending_brief.json"
TTL_SEC = 600  # 10 minutes


def _path() -> Path:
    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    return PENDING_FILE


def clear_pending() -> None:
    p = _path()
    if p.is_file():
        try:
            p.unlink()
        except OSError:
            pass


def load_pending() -> dict[str, Any] | None:
    p = _path()
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        clear_pending()
        return None
    if not isinstance(data, dict):
        clear_pending()
        return None
    created = float(data.get("created_at") or 0)
    if created and (time.time() - created) > TTL_SEC:
        clear_pending()
        return None
    return data


def save_pending(brief: dict[str, Any]) -> None:
    data = dict(brief)
    data["created_at"] = time.time()
    _path().write_text(json.dumps(data, indent=2), encoding="utf-8")
