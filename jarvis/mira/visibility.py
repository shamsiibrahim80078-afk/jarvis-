"""Upload visibility — detect crop risk and ask the user before cutting pixels."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def probe_size(path: str | Path) -> tuple[int, int] | None:
    """Return (width, height) for an image or video file."""
    p = Path(path)
    if not p.is_file():
        return None
    ext = p.suffix.lower()
    if ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"):
        try:
            from PIL import Image

            with Image.open(p) as im:
                w, h = im.size
                if w > 0 and h > 0:
                    return int(w), int(h)
        except Exception:
            return None
    try:
        import imageio_ffmpeg

        ff = imageio_ffmpeg.get_ffmpeg_exe()
        import subprocess

        proc = subprocess.run(
            [ff, "-i", str(p)],
            capture_output=True,
            text=True,
            timeout=20,
        )
        err = proc.stderr or ""
        m = re.search(r"(\d{2,5})x(\d{2,5})", err)
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception:
        return None
    return None


def target_size(aspect: str) -> tuple[int, int]:
    a = (aspect or "16:9").strip().lower()
    if a in ("9:16", "9x16", "vertical", "shorts", "reel", "story", "tiktok"):
        return 1080, 1920
    if a in ("1:1", "square"):
        return 1080, 1080
    return 1920, 1080


def cover_visible_ratio(src_w: int, src_h: int, out_w: int, out_h: int) -> float:
    """Fraction of source pixels kept under cover/crop fit (0–1)."""
    if src_w <= 0 or src_h <= 0 or out_w <= 0 or out_h <= 0:
        return 1.0
    src_ar = src_w / src_h
    out_ar = out_w / out_h
    if src_ar > out_ar:
        # landscape into portrait/taller frame — sides cropped
        return max(0.05, min(1.0, out_ar / src_ar))
    if src_ar < out_ar:
        # taller into wider — top/bottom cropped
        return max(0.05, min(1.0, src_ar / out_ar))
    return 1.0


def analyze_upload_visibility(
    paths: list[str | Path],
    *,
    aspect: str = "9:16",
    min_visible: float = 0.88,
) -> dict[str, Any]:
    """Score whether uploads would stay fully visible at the target aspect."""
    out_w, out_h = target_size(aspect)
    rows: list[dict[str, Any]] = []
    worst = 1.0
    for raw in paths:
        p = Path(raw)
        size = probe_size(p)
        if not size:
            rows.append({"path": str(p), "ok": False, "reason": "unreadable"})
            continue
        w, h = size
        ratio = cover_visible_ratio(w, h, out_w, out_h)
        worst = min(worst, ratio)
        rows.append(
            {
                "path": str(p),
                "name": p.name,
                "width": w,
                "height": h,
                "visible_if_crop": round(ratio, 3),
                "ok": ratio >= min_visible,
            }
        )
    needs_ask = bool(rows) and any(
        (not r.get("ok")) and r.get("visible_if_crop") is not None for r in rows
    )
    # Also ask if any file unreadable
    if any(r.get("reason") == "unreadable" for r in rows):
        needs_ask = True
    suggested = "16:9" if out_w < out_h and worst < min_visible else aspect
    return {
        "needs_ask": needs_ask,
        "worst_visible": round(worst, 3),
        "aspect": aspect,
        "out_size": [out_w, out_h],
        "files": rows,
        "suggested_aspect": suggested,
        "default_fit": "contain",
    }


def visibility_ask_message(analysis: dict[str, Any], topic: str = "") -> str:
    """Short question for Ibrahim when crop would hide content."""
    worst = float(analysis.get("worst_visible") or 0)
    pct = int(round((1.0 - worst) * 100))
    aspect = analysis.get("aspect") or "9:16"
    suggested = analysis.get("suggested_aspect") or "16:9"
    names = [str(f.get("name") or "") for f in (analysis.get("files") or []) if f.get("name")]
    shown = ", ".join(names[:3]) or "your uploads"
    topic_bit = f" for “{(topic or '').strip()[:60]}”" if (topic or "").strip() else ""
    return (
        f"Sir, {shown} won't stay fully visible in {aspect} — about {pct}% would be cropped"
        f"{topic_bit}. "
        "Reply: **show full** (letterbox, recommended), **crop fill**, "
        f"**{suggested}**, or **shorts**. I won't cut pixels until you choose."
    )


def parse_visibility_reply(text: str) -> dict[str, Any] | None:
    """Parse user choice after a visibility ask. None = not a visibility reply."""
    raw = (text or "").strip()
    if not raw:
        return None
    lower = raw.lower()

    # Explicit cancel handled elsewhere
    if re.search(r"\b(cancel|never\s*mind|forget\s+it)\b", lower):
        return {"_cancelled": True}

    fit = None
    aspect = None

    if re.search(
        r"\b(show\s+full|full\s+(?:frame|image|pic|picture|video)|letterbox|contain|"
        r"don'?t\s+crop|do\s+not\s+crop|no\s+crop|poori|puree|pura|poora|"
        r"keep\s+(?:full|all)|without\s+cropp?ing)\b",
        lower,
    ):
        fit = "contain"
    elif re.search(r"\b(crop|fill|cover|zoom\s+fill|tight\s+crop)\b", lower):
        fit = "cover"

    if re.search(r"\b(16\s*[:x]\s*9|landscape|widescreen|horizontal)\b", lower):
        aspect = "16:9"
        fit = fit or "contain"
    elif re.search(r"\b(9\s*[:x]\s*16|shorts?|reels?|portrait|vertical|tiktok)\b", lower):
        aspect = "9:16"
        fit = fit or "contain"
    elif re.search(r"\b(1\s*[:x]\s*1|square)\b", lower):
        aspect = "1:1"
        fit = fit or "contain"

    if re.search(r"\b(go\s+ahead|proceed|just\s+(?:make|do)\s+it|yes|haan|han)\b", lower):
        fit = fit or "contain"

    if fit is None and aspect is None:
        # Only accept short replies that clearly answer the ask
        if re.fullmatch(r"(full|crop|fill|letterbox|contain|cover)", lower):
            fit = "contain" if lower in ("full", "letterbox", "contain") else "cover"
        else:
            return None

    return {
        "fit_mode": fit or "contain",
        "aspect": aspect,
        "confirmed": True,
    }


def resolve_media_for_check(
    *,
    media_paths: list[str] | None = None,
    use_uploads: bool = False,
    limit: int = 6,
) -> list[Path]:
    from jarvis.mira.uploads import resolve_media_paths

    return resolve_media_paths(list(media_paths or []), use_uploads=use_uploads, limit=limit)
