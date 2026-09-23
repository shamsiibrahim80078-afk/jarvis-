"""Remember last Mira output so convert/edit can target it."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
LAST_FILE = ROOT / "data" / "mira" / "last_output.json"


def save_last_output(data: dict[str, Any]) -> None:
    LAST_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "topic": data.get("topic") or data.get("script") or "",
        "video_path": data.get("video_path"),
        "image_path": data.get("image_path"),
        "aspect": data.get("aspect"),
        "mood": data.get("mood"),
        "format": data.get("format"),
        "audio_mode": data.get("audio_mode"),
        "saved_at": time.time(),
    }
    LAST_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_last_output() -> dict[str, Any] | None:
    if not LAST_FILE.is_file():
        return None
    try:
        data = json.loads(LAST_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None
