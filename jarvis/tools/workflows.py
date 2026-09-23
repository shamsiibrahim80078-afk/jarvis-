"""Saved links, folders, and workflow shortcuts."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_PATH = ROOT / "data" / "workflows.json"


def _load() -> dict:
    if not WORKFLOWS_PATH.exists():
        return {"links": {}, "folders": {}}
    try:
        return json.loads(WORKFLOWS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"links": {}, "folders": {}}


def _save(data: dict) -> None:
    WORKFLOWS_PATH.parent.mkdir(parents=True, exist_ok=True)
    WORKFLOWS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_link(name: str) -> str | None:
    data = _load()
    key = name.lower().replace(" ", "_")
    val = data.get("links", {}).get(key) or data.get("links", {}).get(name)
    return val.strip() if isinstance(val, str) and val.strip() else None


def get_sheet_tab_gid(tab_name: str) -> str | None:
    """Fuzzy match tab name to saved gid (ignore empty placeholders)."""
    data = _load()
    tabs = data.get("sheet_tabs", {})
    key = tab_name.lower().strip()

    def _valid(gid: object) -> str | None:
        if gid is None:
            return None
        s = str(gid).strip()
        return s if s.isdigit() else None

    if key in tabs:
        found = _valid(tabs[key])
        if found:
            return found
    for name, gid in tabs.items():
        if key in name or name in key:
            found = _valid(gid)
            if found:
                return found
    return None


def set_sheet_tab(name: str, gid: str) -> str:
    data = _load()
    key = name.lower().strip()
    data.setdefault("sheet_tabs", {})[key] = gid.strip()
    _save(data)
    return f"Saved sheet tab '{name}', sir."


def set_link(name: str, url: str) -> str:
    data = _load()
    key = name.lower().replace(" ", "_").replace("-", "_")
    data.setdefault("links", {})[key] = url.strip()
    _save(data)
    return f"Saved link '{name}', sir."


def get_folder(name: str) -> str | None:
    data = _load()
    key = name.lower().replace(" ", "_")
    return data.get("folders", {}).get(key) or data.get("folders", {}).get(name)


def set_folder(name: str, path: str) -> str:
    data = _load()
    key = name.lower().replace(" ", "_")
    data.setdefault("folders", {})[key] = path.strip()
    _save(data)
    return f"Saved folder '{name}', sir."


def resolve_path(name_or_path: str) -> str:
    """Named folder alias or raw path."""
    named = get_folder(name_or_path)
    if named:
        return named
    p = Path(name_or_path).expanduser()
    return str(p)
