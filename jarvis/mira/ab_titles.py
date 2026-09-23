"""A/B title packaging memory — remember which title styles win."""

from __future__ import annotations

import json
import random
import re
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "data" / "mira" / "ab_titles.json"


def _load() -> dict[str, Any]:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    if not PATH.is_file():
        return {"variants": [], "wins": {}}
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"variants": [], "wins": {}}
    except Exception:
        return {"variants": [], "wins": {}}


def _save(data: dict[str, Any]) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _style_key(title: str) -> str:
    t = (title or "").lower()
    if t.startswith("pov"):
        return "pov"
    if "wait for it" in t:
        return "wait"
    if "nobody talks" in t:
        return "nobody"
    if "you won't believe" in t or "wont believe" in t:
        return "believe"
    if "save this" in t:
        return "save"
    return "plain"


def pick_ab_title(topic: str, pack: dict[str, Any]) -> tuple[str, str, str]:
    """Return (chosen_title, alt_title, style_key). Biases toward historically winning styles."""
    from jarvis.mira.packaging import _clean_topic, _template_pack

    clean = _clean_topic(topic)
    primary = str(pack.get("title") or "")
    alt_pack = _template_pack(clean)
    # Force a different template index
    alt = str(alt_pack.get("title") or primary)
    if alt.lower() == primary.lower():
        alt = f"POV: {clean} #Shorts"[:95]

    data = _load()
    wins = data.get("wins") or {}
    # Weight styles by wins
    cands = [
        (primary, _style_key(primary)),
        (alt, _style_key(alt)),
    ]
    weights = []
    for _, style in cands:
        weights.append(1.0 + float(wins.get(style) or 0) * 0.35)
    chosen_i = random.choices(range(len(cands)), weights=weights, k=1)[0]
    chosen, style = cands[chosen_i]
    other = cands[1 - chosen_i][0]

    variants = list(data.get("variants") or [])
    variants.append(
        {
            "topic": clean[:80],
            "chosen": chosen,
            "alt": other,
            "style": style,
            "at": time.time(),
            "video_id": "",
        }
    )
    data["variants"] = variants[-200:]
    data["last"] = variants[-1]
    _save(data)
    return chosen[:95], other[:95], style


def attach_video_id(video_id: str) -> None:
    if not video_id:
        return
    data = _load()
    last = data.get("last")
    if isinstance(last, dict):
        last["video_id"] = video_id
        data["last"] = last
        variants = list(data.get("variants") or [])
        if variants:
            variants[-1]["video_id"] = video_id
            data["variants"] = variants
        _save(data)


def record_win(style: str) -> None:
    if not style:
        return
    data = _load()
    wins = dict(data.get("wins") or {})
    wins[style] = int(wins.get(style) or 0) + 1
    data["wins"] = wins
    _save(data)


def mark_winner_from_stats(stats_by_video: dict[str, dict[str, Any]]) -> str:
    """Given video_id -> {views,...}, bump win for best recent A/B style."""
    data = _load()
    variants = list(data.get("variants") or [])
    scored: list[tuple[float, str]] = []
    for v in variants[-40:]:
        vid = str(v.get("video_id") or "")
        if not vid or vid not in stats_by_video:
            continue
        views = float((stats_by_video[vid] or {}).get("views") or 0)
        scored.append((views, str(v.get("style") or "plain")))
    if not scored:
        return "No A/B variants with stats yet."
    scored.sort(reverse=True)
    best_style = scored[0][1]
    record_win(best_style)
    return f"A/B winner style: {best_style} ({int(scored[0][0])} views)"
