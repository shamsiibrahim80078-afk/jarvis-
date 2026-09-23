"""Multi-platform export — copy polished Shorts for Reels / TikTok folders."""

from __future__ import annotations

import re
import shutil
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EXPORT_ROOT = ROOT / "data" / "mira" / "exports"


def export_platforms(
    source: str | Path | None = None,
    *,
    platforms: list[str] | None = None,
) -> dict[str, Any]:
    """Export last/current Short into platform folders (same 9:16 file)."""
    from jarvis.mira.edit import latest_video

    src = Path(source) if source else latest_video()
    if not src or not Path(src).is_file():
        return {"ok": False, "message": "No video to export."}
    src = Path(src)

    plats = platforms or ["instagram_reels", "tiktok", "youtube_shorts"]
    stamp = time.strftime("%Y%m%d_%H%M%S")
    stem = re.sub(r"[^a-zA-Z0-9_\-]+", "_", src.stem)[:40]
    outs: list[str] = []
    for p in plats:
        key = re.sub(r"[^a-z0-9_]+", "_", p.lower())
        dest_dir = EXPORT_ROOT / key
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{stamp}_{stem}.mp4"
        try:
            shutil.copy2(src, dest)
            outs.append(str(dest))
        except Exception:
            continue
    if not outs:
        return {"ok": False, "message": "Export failed."}
    return {
        "ok": True,
        "paths": outs,
        "message": "Exported for "
        + ", ".join(Path(p).parent.name for p in outs)
        + f".\n" + "\n".join(outs),
    }


def is_export_intent(text: str) -> bool:
    t = (text or "").lower()
    return bool(
        re.search(
            r"\b(export\s+(?:to\s+)?(?:reels?|tiktok|instagram)|"
            r"save\s+for\s+(?:reels?|tiktok)|multi[\s-]?platform\s+export|"
            r"export\s+(?:last\s+)?(?:short|video|clip))\b",
            t,
        )
    )
