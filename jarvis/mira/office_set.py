"""Locked tech-campus office plates — short prompts, no people, consistent set."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SET_DIR = ROOT / "data" / "mira" / "office_set"
META_PATH = SET_DIR / "office_set.json"

OFFICE = {
    "id": "nexus_campus_v1",
    "name": "Nexus Tech Campus",
    "seed": 77_001_001,
    "dna": (
        "same modern big-tech glass campus office, Microsoft Google style, "
        "daylight, clean desks, no logos no people"
    ),
}

PLATES: list[dict[str, Any]] = [
    {"id": "lobby", "seed_off": 0, "prompt": "{dna}, empty glass lobby reception morning, vertical"},
    {"id": "elevator", "seed_off": 2, "prompt": "{dna}, empty glass elevator doors opening, vertical"},
    {"id": "desk_empty", "seed_off": 4, "prompt": "{dna}, standing desk dual monitors laptop coffee, vertical empty"},
    {"id": "monitors_code", "seed_off": 6, "prompt": "{dna}, close-up dual monitors code IDE keyboard, vertical no people"},
    {"id": "whiteboard_close", "seed_off": 8, "prompt": "{dna}, close-up whiteboard system boxes arrows marker, vertical no people"},
    {"id": "cafeteria", "seed_off": 10, "prompt": "{dna}, empty premium cafeteria lunch trays, vertical no people"},
    {"id": "campus_exterior", "seed_off": 12, "prompt": "{dna}, glass campus exterior courtyard trees morning, vertical"},
    {"id": "campus_evening", "seed_off": 14, "prompt": "{dna}, same glass campus exterior evening lights, vertical"},
    {"id": "deploy_green", "seed_off": 16, "prompt": "{dna}, laptop screen green deploy success checkmark, vertical"},
    {"id": "breakfast_desk", "seed_off": 18, "prompt": "{dna}, breakfast coffee toast beside laptop desk, vertical no people"},
]


def set_dir() -> Path:
    SET_DIR.mkdir(parents=True, exist_ok=True)
    return SET_DIR


def meta() -> dict[str, Any]:
    if META_PATH.is_file():
        try:
            data = json.loads(META_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def _save_meta(data: dict[str, Any]) -> None:
    set_dir()
    META_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def plate_path(plate_id: str) -> Path:
    return set_dir() / f"{plate_id}.jpg"


def ensure_office_plates(*, force: bool = False, vertical: bool = True) -> dict[str, Path]:
    from jarvis.mira.pipeline import _upscale_sharpen, generate_still

    out: dict[str, Path] = {}
    w, h = (768, 1280) if vertical else (1280, 768)
    tw, th = (1080, 1920) if vertical else (1920, 1080)
    plates_meta: dict[str, str] = {}

    for plate in PLATES:
        pid = str(plate["id"])
        dest = plate_path(pid)
        hq = dest.with_name(dest.stem + "_hq.jpg")
        if not force and hq.is_file() and hq.stat().st_size > 40_000:
            out[pid] = hq
            plates_meta[pid] = str(hq)
            continue
        prompt = str(plate["prompt"]).format(dna=OFFICE["dna"])
        seed = int(OFFICE["seed"]) + int(plate.get("seed_off") or 0)
        generate_still(
            prompt,
            dest,
            width=w,
            height=h,
            model="flux",
            seed=seed,
            max_attempts=5,
            timeout=90.0,
            enhance=False,
            raw=True,
        )
        out[pid] = _upscale_sharpen(dest, tw, th)
        plates_meta[pid] = str(out[pid])

    _save_meta(
        {
            "id": OFFICE["id"],
            "name": OFFICE["name"],
            "seed": OFFICE["seed"],
            "dna": OFFICE["dna"],
            "version": "v5_short",
            "plates": plates_meta,
        }
    )
    return out


def get_plate(plate_id: str) -> Path:
    plates = ensure_office_plates()
    if plate_id in plates:
        return plates[plate_id]
    if plates:
        return next(iter(plates.values()))
    raise RuntimeError("Office set plates missing")
