"""Pixabay stock fallback when Pexels misses the brief."""

from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

_UA = "Jarvis-Mira/1.0 (+local personal assistant)"
_VIDEO_SEARCH = "https://pixabay.com/api/videos/"


def api_key() -> str:
    return (os.getenv("PIXABAY_API_KEY") or os.getenv("PIXABAY_KEY") or "").strip()


def configured() -> bool:
    return bool(api_key())


def _http_get(url: str, timeout: float = 45.0) -> tuple[int, bytes]:
    try:
        import httpx

        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": _UA})
            return resp.status_code, resp.content
    except ImportError:
        req = Request(url, headers={"User-Agent": _UA})
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return int(getattr(resp, "status", 200) or 200), resp.read()


def search_videos(query: str, *, count: int = 5) -> list[dict[str, Any]]:
    key = api_key()
    if not key:
        return []
    q = re.sub(r"\s+", " ", (query or "").strip())
    if not q:
        return []
    url = (
        f"{_VIDEO_SEARCH}?key={quote_plus(key)}&q={quote_plus(q)}"
        f"&per_page={max(3, min(20, int(count or 5)))}&video_type=all"
    )
    status, body = _http_get(url, timeout=40.0)
    if status != 200:
        return []
    data = json.loads(body.decode("utf-8", errors="ignore"))
    hits = data.get("hits") if isinstance(data, dict) else None
    if not isinstance(hits, list):
        return []
    out: list[dict[str, Any]] = []
    for h in hits[: max(1, min(15, int(count or 5)))]:
        vids = (h.get("videos") or {}) if isinstance(h, dict) else {}
        # Prefer medium/large
        cand = vids.get("medium") or vids.get("large") or vids.get("small") or {}
        u = cand.get("url") if isinstance(cand, dict) else None
        if not u:
            continue
        out.append(
            {
                "id": h.get("id"),
                "url": u,
                "pageURL": h.get("pageURL"),
                "user": h.get("user"),
                "tags": h.get("tags"),
                "provider": "pixabay",
            }
        )
    return out


def download_video(url: str, dest: Path, timeout: float = 120.0) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    status, body = _http_get(url, timeout=timeout)
    if status != 200 or len(body) < 20_000:
        raise RuntimeError(f"Pixabay download failed HTTP {status}")
    dest.write_bytes(body)
    return dest.resolve()


def fetch_videos(
    topic: str,
    out_dir: Path,
    *,
    count: int = 1,
    brief: str | None = None,
) -> tuple[list[Path], list[dict[str, Any]]]:
    if not configured():
        return [], []
    n = max(1, min(4, int(count or 1)))
    q = (topic or brief or "").strip()
    found = search_videos(q, count=max(5, n + 2))
    paths: list[Path] = []
    credits: list[dict[str, Any]] = []
    for i, vid in enumerate(found[:n]):
        name = f"pixabayvid_{vid.get('id') or uuid.uuid4().hex[:8]}_{i + 1}.mp4"
        dest = out_dir / name
        try:
            if dest.is_file() and dest.stat().st_size > 50_000:
                path = dest.resolve()
            else:
                path = download_video(str(vid["url"]), dest)
            paths.append(path)
            credits.append(
                {
                    "photographer": vid.get("user"),
                    "pixabay_url": vid.get("pageURL"),
                    "provider": "pixabay",
                    "kind": "video",
                    "search_query": q,
                    "tags": vid.get("tags"),
                }
            )
        except Exception:
            continue
    return paths, credits
