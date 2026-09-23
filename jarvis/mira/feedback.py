"""Store ratings so Mira prompt quality improves over time."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from jarvis.mira.quality import rebuild_from_feedback

_STORE = Path(__file__).resolve().parents[2] / "data" / "mira" / "feedback.jsonl"


def _ensure() -> None:
    _STORE.parent.mkdir(parents=True, exist_ok=True)
    if not _STORE.is_file():
        _STORE.write_text("", encoding="utf-8")


def list_feedback(limit: int = 50) -> list[dict[str, Any]]:
    _ensure()
    rows: list[dict[str, Any]] = []
    try:
        for line in _STORE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    except OSError:
        return []
    return rows[-max(1, int(limit)) :]


def rate(
    rating: int,
    *,
    topic: str = "",
    prompt: str = "",
    style: str = "cinematic",
    path: str = "",
    note: str = "",
) -> dict[str, Any]:
    """Record 1–5 rating. 4–5 = keep doing this look; 1–2 = avoid."""
    _ensure()
    score = max(1, min(5, int(rating)))
    row = {
        "id": uuid.uuid4().hex[:12],
        "ts": time.time(),
        "rating": score,
        "topic": (topic or "")[:300],
        "prompt": (prompt or "")[:800],
        "style": (style or "cinematic")[:40],
        "path": (path or "")[:500],
        "note": (note or "")[:300],
    }
    with _STORE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    cfg = rebuild_from_feedback(list_feedback(limit=200))
    return {
        "ok": True,
        "rating": score,
        "id": row["id"],
        "rated_examples": cfg.get("rated_examples"),
        "message": (
            f"Saved rating {score}/5. Mira will lean into what you like "
            f"({cfg.get('rated_examples')} examples)."
        ),
    }
