"""File copy, list, and transfer operations."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from jarvis.tools.command_parse import extract_windows_paths, normalize
from jarvis.tools.workflows import resolve_path


def list_folder(path: str) -> str:
    p = Path(resolve_path(path))
    if not p.exists():
        return f"Folder not found: {path}"
    items = list(p.iterdir())[:30]
    if not items:
        return f"Folder is empty, sir: {p}"
    names = [f"{'[dir]' if i.is_dir() else '[file]'} {i.name}" for i in items]
    return f"Contents of {p.name}: " + ", ".join(names)


def copy_files(from_path: str, to_path: str) -> str:
    src = Path(resolve_path(from_path))
    dst = Path(resolve_path(to_path))
    if not src.exists():
        return f"Source not found: {from_path}"
    dst.mkdir(parents=True, exist_ok=True)

    count = 0
    if src.is_file():
        shutil.copy2(src, dst / src.name)
        return f"Copied {src.name} to {dst}, sir."
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            if target.exists():
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)
        count += 1
    return f"Copied {count} item(s) from {src} to {dst}, sir."


def parse_transfer_command(text: str) -> tuple[str, str] | None:
    """Extract from/to paths from 'copy from X to Y' style commands."""
    lower = normalize(text)
    paths = extract_windows_paths(text)

    m = re.search(
        r"(?:copy|upload|move|transfer|sync)\s+(?:all\s+)?(?:files?\s+)?from\s+(.+?)\s+to\s+(.+)$",
        lower,
    )
    if m:
        return m.group(1).strip(), m.group(2).strip()

    if len(paths) >= 2:
        return paths[0], paths[1]
    return None
