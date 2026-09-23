"""User-uploaded media for Mira — drop files or POST /api/mira/upload.

Priority rule (today's workflow):
  If you uploaded pics/clips recently (or via HUD), Mira uses THEM first
  for the next video — unless you say “stock only” / “without my uploads”.
"""

from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
UPLOAD_DIR = ROOT / "data" / "mira" / "uploads"
ACTIVE_BATCH = UPLOAD_DIR / ".active_batch.json"

# Prefer uploads uploaded/touched within this window (seconds)
RECENT_UPLOAD_SEC = 30 * 60  # 30 min — only “I just uploaded for this ask”
ACTIVE_BATCH_SEC = 45 * 60  # active HUD batch window


_VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}
_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
_ALLOWED = _VIDEO_EXT | _IMAGE_EXT


def uploads_dir() -> Path:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return UPLOAD_DIR


def is_media_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in _ALLOWED


def is_video(path: Path) -> bool:
    return path.suffix.lower() in _VIDEO_EXT


def is_image(path: Path) -> bool:
    return path.suffix.lower() in _IMAGE_EXT


def _safe_name(name: str) -> str:
    base = Path(name).name
    stem = re.sub(r"[^a-zA-Z0-9._-]+", "_", Path(base).stem)[:48].strip("._") or "media"
    ext = Path(base).suffix.lower()
    if ext not in _ALLOWED:
        ext = ".mp4"
    return f"{stem}_{uuid.uuid4().hex[:8]}{ext}"


def _write_active_batch(paths: list[Path]) -> None:
    """Mark this upload set as the preferred pack for the next Mira video."""
    uploads_dir()
    names = [p.name for p in paths if is_media_file(p)]
    payload = {
        "updated_at": time.time(),
        "files": names,
        "count": len(names),
    }
    try:
        ACTIVE_BATCH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        pass


def mark_active_batch(paths: list[str | Path] | None = None) -> None:
    """Public: refresh active batch (HUD upload or drop)."""
    if paths:
        _write_active_batch([Path(p) for p in paths])
        return
    rows = list_uploads(limit=12)
    _write_active_batch([Path(r["path"]) for r in rows])


def clear_active_batch() -> None:
    try:
        if ACTIVE_BATCH.is_file():
            ACTIVE_BATCH.unlink()
    except OSError:
        pass


def load_active_batch() -> dict[str, Any] | None:
    if not ACTIVE_BATCH.is_file():
        return None
    try:
        data = json.loads(ACTIVE_BATCH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def save_upload(filename: str, data: bytes) -> Path:
    """Persist raw bytes into uploads folder. Returns dest path."""
    if not data:
        raise ValueError("empty upload")
    dest = uploads_dir() / _safe_name(filename)
    dest.write_bytes(data)
    batch = load_active_batch() or {}
    names = list(batch.get("files") or [])
    if dest.name not in names:
        names.insert(0, dest.name)
    try:
        ACTIVE_BATCH.write_text(
            json.dumps(
                {"updated_at": time.time(), "files": names[:24], "count": len(names[:24])},
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass
    return dest.resolve()


def import_path(src: str | Path) -> Path | None:
    """Copy an existing local file into uploads (if not already there)."""
    p = Path(src).expanduser()
    if not is_media_file(p):
        return None
    try:
        resolved = p.resolve()
    except OSError:
        return None
    up = uploads_dir().resolve()
    if resolved.parent == up:
        mark_active_batch([resolved])
        return resolved
    dest = up / _safe_name(resolved.name)
    shutil.copy2(resolved, dest)
    mark_active_batch([dest])
    return dest.resolve()


def list_uploads(*, limit: int = 40) -> list[dict[str, Any]]:
    d = uploads_dir()
    rows: list[dict[str, Any]] = []
    for p in d.iterdir():
        if not is_media_file(p):
            continue
        st = p.stat()
        rows.append(
            {
                "name": p.name,
                "path": str(p.resolve()),
                "kind": "video" if is_video(p) else "image",
                "bytes": st.st_size,
                "mtime": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
                .replace(microsecond=0)
                .isoformat(),
                "mtime_ts": st.st_mtime,
            }
        )
    rows.sort(key=lambda r: r.get("mtime_ts") or 0, reverse=True)
    return rows[: max(1, min(100, int(limit or 40)))]


def recent_uploads(*, within_sec: float = RECENT_UPLOAD_SEC, limit: int = 12) -> list[dict[str, Any]]:
    """Uploads touched within the window — newest first."""
    now = time.time()
    out: list[dict[str, Any]] = []
    for row in list_uploads(limit=40):
        ts = float(row.get("mtime_ts") or 0)
        if ts and (now - ts) <= within_sec:
            out.append(row)
        if len(out) >= limit:
            break
    return out


def resolve_media_paths(
    paths: list[str] | None = None,
    *,
    use_uploads: bool = False,
    limit: int = 8,
) -> list[Path]:
    """Resolve explicit paths and/or uploads. Prefer active batch / recent files."""
    out: list[Path] = []
    seen: set[str] = set()
    had_explicit = bool(paths)

    def _add(p: Path) -> None:
        if not is_media_file(p):
            return
        key = str(p.resolve())
        if key in seen:
            return
        seen.add(key)
        out.append(p.resolve())

    for raw in paths or []:
        raw = (raw or "").strip().strip('"').strip("'")
        if not raw:
            continue
        p = Path(raw).expanduser()
        if is_media_file(p):
            _add(p)
            continue
        cand = uploads_dir() / Path(raw).name
        if is_media_file(cand):
            _add(cand)

    if had_explicit:
        return out[: max(1, min(12, int(limit or 8)))] if out else []

    if use_uploads and not out:
        batch = load_active_batch()
        if batch and isinstance(batch.get("files"), list):
            for name in batch["files"]:
                cand = uploads_dir() / str(name)
                _add(cand)
                if len(out) >= limit:
                    break
        if len(out) < limit:
            for row in recent_uploads(limit=limit):
                _add(Path(row["path"]))
                if len(out) >= limit:
                    break
        if not out:
            for row in list_uploads(limit=limit):
                _add(Path(row["path"]))
                if len(out) >= limit:
                    break

    # Prefer real motion inside YOUR pack: videos first, then images
    videos = [p for p in out if is_video(p)]
    images = [p for p in out if is_image(p)]
    ordered = videos + images
    return ordered[: max(0, min(12, int(limit or 8)))]


def has_uploads(*, min_count: int = 1) -> bool:
    return len(list_uploads(limit=max(1, min_count))) >= max(1, int(min_count or 1))


def wants_stock_only(text: str) -> bool:
    lower = (text or "").lower()
    return bool(
        re.search(
            r"\b(without\s+(?:my\s+)?uploads?|stock\s+only|from\s+pexels|no\s+uploads?|"
            r"don'?t\s+use\s+(?:my\s+)?uploads?|"
            r"ignore\s+(?:my\s+)?uploads?)\b",
            lower,
        )
    )


def wants_user_media(text: str) -> bool:
    lower = (text or "").lower()
    return bool(
        re.search(
            r"\b(use\s+my\s+uploads?|from\s+my\s+uploads?|with\s+my\s+uploads?|"
            r"using\s+(?:my\s+)?uploads?|using\s+uploaded|"
            r"uploaded\s+(?:media|clips?|videos?|images?|photos?|pictures?)|"
            r"my\s+uploads?|"
            r"edit\s+my\s+uploads?|"
            r"using\s+these\s+(?:uploaded\s+)?(?:clips?|videos?|images?|photos?)|"
            r"from\s+(?:these|the)\s+(?:pics?|pictures?|photos?|images?|clips?|videos?)|"
            r"with\s+(?:these|my)\s+(?:pics?|pictures?|photos?|images?|clips?|videos?))\b",
            lower,
        )
    )


def should_use_uploads(text: str = "") -> bool:
    """Use uploads ONLY when the user explicitly asks for their media.

    Never auto-hijack a new “make a video about X” with an old active batch —
    that caused A-visuals + B-voice (stuck on the previous idea).
    Fresh HUD uploads still work via: “using my uploads” / “from these pics”.
    """
    if wants_stock_only(text):
        return False
    if wants_user_media(text):
        return True
    return False
