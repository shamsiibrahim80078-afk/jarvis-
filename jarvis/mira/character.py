"""Locked Mira office character — one face (Alex). Short prompts for Pollinations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CHAR_DIR = ROOT / "data" / "mira" / "characters" / "alex"
META_PATH = CHAR_DIR / "character.json"

ALEX = {
    "id": "alex",
    "name": "Alex",
    "role": "AI systems engineer",
    "seed": 42_424_242,
    "dna": (
        "same man Alex, South Asian, short black hair, full dark beard, "
        "light blue polo shirt, photoreal, no glasses"
    ),
}

# Scene-first short prompts (Pollinations ignores long tails)
POSES: list[dict[str, Any]] = [
    {
        "id": "talk_cam",
        "seed_off": 0,
        "prompt": (
            "vertical selfie in modern glass tech office elevator, "
            "{dna}, talking to camera, eye contact, big-tech campus, no logo"
        ),
    },
    {
        "id": "desk_talk",
        "seed_off": 3,
        "prompt": (
            "vertical portrait at standing desk dual monitors glass office, "
            "{dna}, talking to camera, Microsoft Google style campus, no logo"
        ),
    },
    {
        "id": "desk_coding",
        "seed_off": 7,
        "prompt": (
            "vertical side view coding at dual monitors keyboard, "
            "{dna}, focused, modern open tech office daylight, no logo"
        ),
    },
    {
        "id": "whiteboard",
        "seed_off": 11,
        "prompt": (
            "vertical man at whiteboard drawing architecture boxes arrows, "
            "{dna}, marker in hand, glass tech office, not coding, no logo"
        ),
    },
    {
        "id": "coffee_talk",
        "seed_off": 13,
        "prompt": (
            "vertical portrait holding coffee in office cafeteria, "
            "{dna}, talking to camera, modern campus cafe, no logo"
        ),
    },
    {
        "id": "lunch",
        "seed_off": 17,
        "prompt": (
            "vertical sitting with lunch tray in tech campus cafeteria, "
            "{dna}, modern glass cafeteria, no logo"
        ),
    },
    {
        "id": "arrive",
        "seed_off": 19,
        "prompt": (
            "vertical walking into glass office lobby with badge, "
            "{dna}, big-tech campus lobby daylight, no logo"
        ),
    },
    {
        "id": "wrap_talk",
        "seed_off": 23,
        "prompt": (
            "vertical evening outside glass tech campus talking to camera, "
            "{dna}, warm lights, no logo"
        ),
    },
    {
        "id": "review",
        "seed_off": 29,
        "prompt": (
            "vertical at desk reviewing code on monitor, "
            "{dna}, slight turn to camera, dual screens tech office, no logo"
        ),
    },
    {
        "id": "meeting",
        "seed_off": 31,
        "prompt": (
            "vertical in glass meeting room with laptop, "
            "{dna}, talking to camera, modern campus, no logo"
        ),
    },
]


def character_dir() -> Path:
    CHAR_DIR.mkdir(parents=True, exist_ok=True)
    return CHAR_DIR


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
    character_dir()
    META_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def pose_path(pose_id: str) -> Path:
    return character_dir() / f"{pose_id}.jpg"


def ensure_character_stills(*, force: bool = False, vertical: bool = True) -> dict[str, Path]:
    from jarvis.mira.pipeline import _upscale_sharpen, generate_still

    out: dict[str, Path] = {}
    w, h = (768, 1280) if vertical else (1280, 768)
    tw, th = (1080, 1920) if vertical else (1920, 1080)
    poses_meta: dict[str, str] = {}

    for pose in POSES:
        pid = str(pose["id"])
        dest = pose_path(pid)
        hq = dest.with_name(dest.stem + "_hq.jpg")
        if not force and hq.is_file() and hq.stat().st_size > 40_000:
            out[pid] = hq
            poses_meta[pid] = str(hq)
            continue

        prompt = str(pose["prompt"]).format(dna=ALEX["dna"])
        seed = int(ALEX["seed"]) + int(pose.get("seed_off") or 0)
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
        poses_meta[pid] = str(out[pid])

    _save_meta(
        {
            "id": ALEX["id"],
            "name": ALEX["name"],
            "role": ALEX["role"],
            "seed": ALEX["seed"],
            "dna": ALEX["dna"],
            "version": "v5_short",
            "poses": poses_meta,
        }
    )
    return out


def talking_still(prefer: str = "talk_cam") -> Path:
    stills = ensure_character_stills()
    if prefer in stills:
        return stills[prefer]
    if stills:
        return next(iter(stills.values()))
    raise RuntimeError("Failed to create locked character stills for Alex")


def cycle_talking_still(index: int = 0) -> Path:
    stills = ensure_character_stills()
    keys = [str(p["id"]) for p in POSES if str(p["id"]) in stills]
    if not keys:
        return talking_still()
    return stills[keys[int(index) % len(keys)]]


def pose_still(pose_id: str) -> Path:
    stills = ensure_character_stills()
    if pose_id in stills:
        return stills[pose_id]
    return talking_still("talk_cam")
