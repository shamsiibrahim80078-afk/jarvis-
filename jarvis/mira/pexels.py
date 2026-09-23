"""Pexels free stock stills + videos for Mira — legal free API (no Google scrape).

Requires ``PEXELS_API_KEY`` in ``.env`` (free at https://www.pexels.com/api/).
Default limits: 200 req/hour, 20_000/month. Attribution recommended.
"""

from __future__ import annotations

import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

_PEXELS_SEARCH = "https://api.pexels.com/v1/search"
_PEXELS_VIDEO_SEARCH = "https://api.pexels.com/videos/search"
_UA = "Jarvis-Mira/1.0 (+local personal assistant)"


def api_key() -> str:
    key = (os.getenv("PEXELS_API_KEY") or os.getenv("PEXELS_KEY") or "").strip()
    if key:
        return key
    try:
        from pathlib import Path

        from dotenv import load_dotenv

        root = Path(__file__).resolve().parents[2]
        load_dotenv(root / ".env", override=False)
    except Exception:
        pass
    return (os.getenv("PEXELS_API_KEY") or os.getenv("PEXELS_KEY") or "").strip()


def configured() -> bool:
    return bool(api_key())


def _http_get(url: str, headers: dict[str, str], timeout: float = 45.0) -> tuple[int, bytes, str]:
    try:
        import httpx

        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(url, headers=headers)
            ctype = (resp.headers.get("content-type") or "").lower()
            return resp.status_code, resp.content, ctype
    except ImportError:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310
            ctype = (resp.headers.get("Content-Type") or "").lower()
            return int(getattr(resp, "status", 200) or 200), resp.read(), ctype


def search_photos(
    query: str,
    *,
    count: int = 5,
    orientation: str = "landscape",
    per_page: int = 15,
) -> list[dict[str, Any]]:
    """Search Pexels once — returns photo metadata + best image URLs."""
    key = api_key()
    if not key:
        return []
    q = re.sub(r"\s+", " ", (query or "").strip())
    if not q:
        return []
    n = max(1, min(15, int(count or 5)))
    orient = orientation if orientation in ("landscape", "portrait", "square") else "landscape"
    url = (
        f"{_PEXELS_SEARCH}?query={quote_plus(q)}"
        f"&per_page={max(n, min(80, int(per_page or 15)))}"
        f"&orientation={orient}"
    )
    status, body, ctype = _http_get(
        url,
        headers={"Authorization": key, "User-Agent": _UA},
        timeout=40.0,
    )
    if status != 200:
        raise RuntimeError(f"Pexels search HTTP {status}")
    import json

    data = json.loads(body.decode("utf-8", errors="ignore"))
    photos = data.get("photos") if isinstance(data, dict) else None
    if not isinstance(photos, list):
        return []
    out: list[dict[str, Any]] = []
    for ph in photos:
        if not isinstance(ph, dict):
            continue
        src = ph.get("src") if isinstance(ph.get("src"), dict) else {}
        # Prefer large / large2x for quality
        img_url = (
            src.get("large2x")
            or src.get("large")
            or src.get("original")
            or src.get("medium")
        )
        if not img_url:
            continue
        out.append(
            {
                "id": ph.get("id"),
                "url": img_url,
                "photographer": ph.get("photographer") or "Pexels",
                "photographer_url": ph.get("photographer_url") or "",
                "pexels_url": ph.get("url") or "https://www.pexels.com",
                "alt": ph.get("alt") or q,
            }
        )
        if len(out) >= n:
            break
    return out


def download_photo(url: str, dest: Path, timeout: float = 60.0) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    status, body, ctype = _http_get(
        url,
        headers={"User-Agent": _UA},
        timeout=timeout,
    )
    if status != 200 or len(body) < 3000:
        raise RuntimeError(f"Pexels download failed HTTP {status}")
    if "png" in ctype:
        if dest.suffix.lower() != ".png":
            dest = dest.with_suffix(".png")
    dest.write_bytes(body)
    return dest.resolve()


def fetch_stills(
    topic: str,
    out_dir: Path,
    *,
    count: int = 5,
    orientation: str = "landscape",
    brief: str | None = None,
) -> tuple[list[Path], list[dict[str, Any]]]:
    """One search + download ``count`` stills. Rejects letter-toy junk."""
    if not configured():
        return [], []
    brief_text = (brief or topic or "").strip()
    queries = [topic]
    try:
        from jarvis.mira.intent import expand_ask

        ex = expand_ask(brief_text or topic)
        qs = [str(q) for q in (ex.get("search_queries") or []) if str(q).strip()]
        if qs:
            queries = qs
    except Exception:
        pass

    photos: list[dict[str, Any]] = []
    seen: set[Any] = set()
    for q in queries[:4]:
        try:
            found = search_photos(q, count=max(count, 6), orientation=orientation)
        except Exception:
            found = []
        for ph in found:
            pid = ph.get("id")
            if pid in seen:
                continue
            seen.add(pid)
            meta = f"{ph.get('pexels_url') or ''} {ph.get('alt') or ''}"
            rel = visual_relevance(
                brief_text or topic,
                query=q,
                pexels_url=str(ph.get("pexels_url") or ""),
                alt=str(ph.get("alt") or ""),
            )
            if not rel.get("ok"):
                continue
            ph["_relevance"] = rel
            photos.append(ph)
        if len(photos) >= count:
            break

    paths: list[Path] = []
    credits: list[dict[str, Any]] = []
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", (topic or "pexels")[:30]).strip("_").lower() or "pexels"
    for i, ph in enumerate(photos[:count]):
        name = f"pexels_{slug}_{ph.get('id') or uuid.uuid4().hex[:8]}_{i + 1}.jpg"
        dest = out_dir / name
        try:
            paths.append(download_photo(str(ph["url"]), dest))
            credits.append(
                {
                    "photographer": ph.get("photographer"),
                    "photographer_url": ph.get("photographer_url"),
                    "pexels_url": ph.get("pexels_url"),
                    "provider": "pexels",
                    "relevance": ph.get("_relevance"),
                }
            )
        except Exception:
            continue
        if i + 1 < len(photos):
            time.sleep(0.35)
    return paths, credits


def attribution_line(credits: list[dict[str, Any]]) -> str:
    if not credits:
        return "Media provided by Pexels (https://www.pexels.com)."
    names = []
    kinds = set()
    for c in credits[:6]:
        n = (c.get("photographer") or c.get("videographer") or "").strip()
        if n and n not in names:
            names.append(n)
        kinds.add((c.get("kind") or "photo").lower())
    people = ", ".join(names) if names else "Pexels contributors"
    label = "Videos" if kinds == {"video"} else ("Photos & videos" if "video" in kinds else "Photos")
    return f"{label} by {people} via Pexels — https://www.pexels.com"


def _pick_video_file(video: dict[str, Any], *, prefer_portrait: bool) -> Optional[str]:
    files = video.get("video_files") if isinstance(video.get("video_files"), list) else []
    scored: list[tuple[int, str]] = []
    for f in files:
        if not isinstance(f, dict):
            continue
        link = (f.get("link") or "").strip()
        if not link:
            continue
        # Skip tiny previews / non-video when file_type present
        ft = str(f.get("file_type") or "").lower()
        if ft and "video" not in ft and "mp4" not in ft:
            continue
        w = int(f.get("width") or 0)
        h = int(f.get("height") or 0)
        if w < 640 or h < 640:
            continue
        quality = str(f.get("quality") or "").lower()
        portrait = h > w
        score = 0
        if prefer_portrait and portrait:
            score += 2000
        elif (not prefer_portrait) and (not portrait):
            score += 2000
        # Prefer 720–1080 HD; avoid huge UHD downloads (speed)
        if quality == "hd":
            score += 1500
        elif quality == "sd":
            score -= 800
        elif quality == "uhd":
            score -= 400  # heavy / slow
        long_edge = max(w, h)
        if 720 <= long_edge <= 1280:
            score += 900
        elif 1280 < long_edge <= 1920:
            score += 500
        elif long_edge > 1920:
            score -= 400
        else:
            score -= 200
        size = int(f.get("size") or 0)
        # Soft penalty for huge files (>12MB) — faster downloads
        if size > 12_000_000:
            score -= 400
        if size > 25_000_000:
            score -= 600
        scored.append((score, link))
    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


def search_videos(
    query: str,
    *,
    count: int = 3,
    orientation: str = "portrait",
    per_page: int = 15,
) -> list[dict[str, Any]]:
    """Search Pexels videos — returns metadata + best download URL."""
    key = api_key()
    if not key:
        return []
    q = re.sub(r"\s+", " ", (query or "").strip())
    if not q:
        return []
    n = max(1, min(10, int(count or 3)))
    orient = orientation if orientation in ("landscape", "portrait", "square") else "portrait"
    url = (
        f"{_PEXELS_VIDEO_SEARCH}?query={quote_plus(q)}"
        f"&per_page={max(n, min(40, int(per_page or 15)))}"
        f"&orientation={orient}"
    )
    status, body, _ctype = _http_get(
        url,
        headers={"Authorization": key, "User-Agent": _UA},
        timeout=45.0,
    )
    if status != 200:
        raise RuntimeError(f"Pexels video search HTTP {status}")
    import json

    data = json.loads(body.decode("utf-8", errors="ignore"))
    videos = data.get("videos") if isinstance(data, dict) else None
    if not isinstance(videos, list):
        return []
    prefer_portrait = orient == "portrait"
    out: list[dict[str, Any]] = []
    for vid in videos:
        if not isinstance(vid, dict):
            continue
        link = _pick_video_file(vid, prefer_portrait=prefer_portrait)
        if not link:
            continue
        user = vid.get("user") if isinstance(vid.get("user"), dict) else {}
        out.append(
            {
                "id": vid.get("id"),
                "url": link,
                "duration": vid.get("duration"),
                "width": vid.get("width"),
                "height": vid.get("height"),
                "photographer": user.get("name") or "Pexels",
                "photographer_url": user.get("url") or "",
                "pexels_url": vid.get("url") or "https://www.pexels.com",
                "kind": "video",
                "search_query": q,
            }
        )
        if len(out) >= n:
            break
    return out


def download_video(url: str, dest: Path, timeout: float = 120.0) -> Path:
    dest = dest.with_suffix(".mp4")
    dest.parent.mkdir(parents=True, exist_ok=True)
    status, body, _ctype = _http_get(
        url,
        headers={"User-Agent": _UA},
        timeout=timeout,
    )
    if status != 200 or len(body) < 50_000:
        raise RuntimeError(f"Pexels video download failed HTTP {status} size={len(body)}")
    dest.write_bytes(body)
    return dest.resolve()


def _pexels_query_variants(topic: str) -> list[str]:
    """Short Pexels-friendly queries — long phrases return random stock."""
    # Brand/entity expansions first (google → search laptop scenes, not letter toys)
    try:
        from jarvis.mira.intent import expand_ask

        ex = expand_ask(topic)
        if ex.get("_via") in ("entity_expand", "thin_topic_expand"):
            out = [str(q).strip()[:80] for q in (ex.get("search_queries") or []) if str(q).strip()]
            if out:
                return out[:6]
    except Exception:
        pass
    raw = re.sub(r"\s+", " ", (topic or "").strip())
    raw = re.sub(
        r"\b(make|create|generate|video|clip|reel|about|please|cinematic|motion|"
        r"detail|atmosphere|mood|lifestyle|wide|close|up|establishing|action|"
        r"people|portrait|hd|4k|beautiful|amazing)\b",
        " ",
        raw,
        flags=re.I,
    )
    raw = re.sub(r"\s+", " ", raw).strip()
    words = [w for w in re.findall(r"[a-zA-Z0-9]+", raw) if len(w) > 2]
    variants: list[str] = []
    if words:
        variants.append(" ".join(words[:4]))
        if len(words) >= 2:
            variants.append(" ".join(words[:2]))
        if len(words) >= 3:
            variants.append(words[0] + " " + words[-1])
        variants.append(words[0])
        syn = _TOPIC_SYNONYMS.get(words[0].lower()) or _TOPIC_SYNONYMS.get(words[0].lower().rstrip("s"))
        if syn:
            variants.insert(0, syn[0])
            variants.append(f"{words[0]} {syn[0]}")
    if topic and len(topic.split()) <= 5:
        variants.insert(0, re.sub(r"\s+", " ", topic.strip())[:80])
    seen: set[str] = set()
    out: list[str] = []
    for v in variants:
        key = v.lower().strip()
        if key and key not in seen and len(key) > 1:
            seen.add(key)
            out.append(v.strip())
    return out[:6]


# Brief↔stock synonyms so "dogs" matches puppy/dog clips, etc.
_TOPIC_SYNONYMS: dict[str, list[str]] = {
    "dog": ["puppy", "canine", "pet dog", "dogs"],
    "dogs": ["dog", "puppy", "canine", "pet"],
    "puppy": ["dog", "dogs", "canine"],
    "cat": ["kitten", "feline", "cats"],
    "cats": ["cat", "kitten", "feline"],
    "coffee": ["espresso", "cafe", "cappuccino", "latte", "brew"],
    "espresso": ["coffee", "cafe", "latte"],
    "cafe": ["coffee", "espresso", "barista"],
    "ocean": ["sea", "waves", "beach", "surf"],
    "beach": ["ocean", "waves", "shore", "sand"],
    "car": ["auto", "vehicle", "automobile", "driving"],
    "cars": ["car", "vehicle", "automobile"],
    "food": ["meal", "cooking", "cuisine", "dish"],
    "city": ["urban", "skyline", "downtown", "street"],
    "nature": ["forest", "trees", "landscape", "outdoors"],
    "rain": ["rainfall", "storm", "umbrella", "wet"],
    "snow": ["winter", "snowfall", "blizzard"],
    "music": ["musician", "concert", "guitar", "piano"],
    "space": ["galaxy", "stars", "cosmos", "nebula"],
    "tokyo": ["japan", "neon", "shinjuku", "shibuya"],
    "volcano": ["lava", "eruption", "magma"],
    "lava": ["volcano", "magma", "eruption"],
    # Brands: do NOT synonym-expand to "logo" alone (letter stamps). Use intent.py queries.
}


def _expand_tokens(tokens: set[str]) -> set[str]:
    """Expand brief tokens with true synonyms — never free-associate (google≠logo alone)."""
    out = set(tokens)
    for t in list(tokens):
        syns = list(_TOPIC_SYNONYMS.get(t, [])) + list(_TOPIC_SYNONYMS.get(t.rstrip("s"), []))
        for s in syns:
            sw = [w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 2]
            if not sw:
                continue
            # Compound synonym that includes the token ("google logo") → keep only
            # words that are the token itself (URL must still say google, not just logo)
            if t in sw or t.rstrip("s") in sw:
                continue
            # True alternate ("dogs" ↔ "puppy")
            out.update(sw)
        if t.endswith("s") and len(t) > 3:
            out.add(t[:-1])
        else:
            out.add(t + "s")
    return out


def visual_relevance(
    brief: str,
    *,
    query: str = "",
    pexels_url: str = "",
    path: str = "",
    alt: str = "",
) -> dict[str, Any]:
    """Score whether a clip's *real* metadata matches the brief.

    NEVER treat the search query as evidence — that always matches and lets
    random Pexels results through (wrong visuals + on-topic VO).
    Only Pexels page URL slug + alt/description count.
    """
    from jarvis.mira.brief_match import tokenize

    brief_t = tokenize(brief)
    if not brief_t:
        return {"ok": True, "score": 1.0, "reason": "empty_brief"}

    meta = " ".join(
        [
            (pexels_url or "").replace("-", " ").replace("_", " ").replace("/", " "),
            (alt or "").replace("-", " ").replace("_", " "),
        ]
    ).lower()
    if not meta.strip() and path:
        leaf = Path(path).name if path else ""
        leaf = re.sub(r"^pexelsvid_", "", leaf, flags=re.I)
        leaf = re.sub(r"_\d+\.mp4$", "", leaf, flags=re.I)
        if not re.match(r"^\d", leaf) and "pexelsvid" not in leaf.lower():
            meta = leaf.replace("-", " ").replace("_", " ")

    if not meta.strip():
        return {"ok": False, "score": 0.0, "matched": [], "reason": "no_visual_evidence"}

    # Letter-toy / stamp junk that "spells" the brand — never a real scene
    try:
        from jarvis.mira.intent import detect_entity, is_junk_stock_meta

        ent = detect_entity(brief) or detect_entity(query)
        if is_junk_stock_meta(meta, entity=ent):
            return {
                "ok": False,
                "score": 0.0,
                "matched": [],
                "reason": "junk_letter_stock",
            }
    except Exception:
        pass

    meta_t = tokenize(meta)
    meta_exp = _expand_tokens(meta_t)

    # Prefer matching core entity nouns (google, dogs) over every filler word in expanded briefs
    core_brief = brief
    scene_ok: set[str] = set()
    ent: str | None = None
    try:
        from jarvis.mira.intent import expand_ask, detect_entity, entity_scene_tokens

        ent = detect_entity(brief) or detect_entity(query)
        if ent:
            core_brief = ent
            scene_ok = set(entity_scene_tokens(ent))
        else:
            ex = expand_ask(brief)
            if ex.get("original"):
                core_brief = str(ex["original"])
    except Exception:
        pass
    brief_t = tokenize(core_brief) or tokenize(brief)
    if not brief_t:
        return {"ok": True, "score": 1.0, "reason": "empty_brief"}

    hit: set[str] = set()
    for b in brief_t:
        want = _expand_tokens({b})
        for m in meta_exp | meta_t:
            if m in want or b == m or (len(b) >= 4 and (b in m or m in b)):
                hit.add(b)
                break
            if len(b) >= 3 and len(m) >= 3 and (b.rstrip("s") == m.rstrip("s")):
                hit.add(b)
                break
    if not hit:
        for b in brief_t:
            if _expand_tokens({b}) & meta_exp:
                hit.add(b)

    # Brands: stock rarely puts "google" in alt — accept real scene words instead
    scene_hits: set[str] = set()
    if ent and scene_ok and not hit:
        for m in meta_t | meta_exp:
            if m in scene_ok or any(s in m or m in s for s in scene_ok if len(s) >= 4):
                scene_hits.add(m)
        if len(scene_hits) >= 2 or (len(scene_hits) >= 1 and any(
            x in meta for x in ("laptop", "phone", "computer", "screen", "browser", "search")
        )):
            hit = {ent} | scene_hits

    score = len(hit) / max(1, len(brief_t))

    officeish = bool(re.search(r"\b(office|workplace|coworker|cubicle|meeting.?room)\b", meta, re.I))
    brief_office = bool(
        re.search(r"\b(office|workplace|coworker|meeting|startup|desk)\b", brief or "", re.I)
    )
    if officeish and not brief_office and not ent:
        return {
            "ok": False,
            "score": 0.0,
            "matched": sorted(hit),
            "reason": "office_fallback_reject",
        }

    # Product / API / docs asks must never accept fashion / beauty portraits
    productish = bool(
        re.search(
            r"\b(api|sdk|docs?|dashboard|console|saas|software|website|login|"
            r"endpoint|developer|platform|token|oauth|webhook)\b",
            brief or "",
            re.I,
        )
    )
    portraitish = bool(
        re.search(
            r"\b(portrait|fashion|model|beauty|selfie|influencer|woman|man|"
            r"girl|boy|face|makeup|glamour)\b",
            meta,
            re.I,
        )
    )
    uiish = bool(
        re.search(
            r"\b(screen|laptop|monitor|website|dashboard|interface|ui|docs?|"
            r"browser|code|keyboard|app)\b",
            meta,
            re.I,
        )
    )
    if productish and portraitish and not uiish:
        return {
            "ok": False,
            "score": 0.0,
            "matched": sorted(hit),
            "reason": "portrait_for_product_reject",
        }

    ok = bool(hit) and score >= 0.45
    if len(brief_t) == 1 and hit:
        ok = True
    if len(hit) >= 2:
        ok = True
    if ent and scene_hits and hit:
        ok = True

    return {
        "ok": ok,
        "score": round(score, 3),
        "matched": sorted(hit),
        "reason": ("entity_scene_match" if scene_hits else "visual_match") if ok else "visual_mismatch",
        "query_ignored": True,
    }



def fetch_videos(
    topic: str,
    out_dir: Path,
    *,
    count: int = 1,
    orientation: str = "portrait",
    brief: str | None = None,
) -> tuple[list[Path], list[dict[str, Any]]]:
    """Search + download clips that match ``brief`` (defaults to topic). Never office-pad."""
    if not configured():
        return [], []
    brief_text = (brief or topic or "").strip()
    n = max(1, min(5, int(count or 1)))
    # Try short variants — long director phrases often return junk
    variants = _pexels_query_variants(topic)
    if not variants:
        variants = [topic]

    candidates: list[dict[str, Any]] = []
    seen_ids: set[Any] = set()
    for vq in variants:
        try:
            found = search_videos(vq, count=max(5, n + 2), orientation=orientation)
        except Exception:
            found = []
        for vid in found:
            vid_id = vid.get("id")
            if vid_id in seen_ids:
                continue
            seen_ids.add(vid_id)
            rel = visual_relevance(
                brief_text,
                query=vq,
                pexels_url=str(vid.get("pexels_url") or ""),
            )
            vid["_relevance"] = rel
            vid["_used_query"] = vq
            candidates.append(vid)

    # Prefer on-brief clips; fall back to best score only if needed
    ranked = sorted(
        candidates,
        key=lambda v: (
            1 if (v.get("_relevance") or {}).get("ok") else 0,
            float((v.get("_relevance") or {}).get("score") or 0),
        ),
        reverse=True,
    )
    good = [v for v in ranked if (v.get("_relevance") or {}).get("ok")]
    pick = good[:n] if good else []

    paths: list[Path] = []
    credits: list[dict[str, Any]] = []
    for i, vid in enumerate(pick):
        # Name by Pexels id only — do NOT bake the brief into the filename
        # (that would fake visual_relevance matches)
        name = f"pexelsvid_{vid.get('id') or uuid.uuid4().hex[:8]}_{i + 1}.mp4"
        dest = out_dir / name
        try:
            if dest.is_file() and dest.stat().st_size > 50_000:
                path = dest.resolve()
            else:
                path = download_video(str(vid["url"]), dest)
            # Re-check using only Pexels page URL (authoritative)
            rel = visual_relevance(
                brief_text,
                query=str(vid.get("_used_query") or topic),
                pexels_url=str(vid.get("pexels_url") or ""),
            )
            if not rel.get("ok"):
                continue
            paths.append(path)
            credits.append(
                {
                    "photographer": vid.get("photographer"),
                    "photographer_url": vid.get("photographer_url"),
                    "pexels_url": vid.get("pexels_url"),
                    "provider": "pexels",
                    "kind": "video",
                    "search_query": vid.get("_used_query") or topic,
                    "relevance": rel,
                }
            )
        except Exception:
            continue
    if not paths:
        # Pixabay fallback when Pexels misses
        try:
            from jarvis.mira import pixabay as pixabay_mod

            if pixabay_mod.configured():
                p2, c2 = pixabay_mod.fetch_videos(topic, out_dir, count=n, brief=brief_text)
                paths.extend(p2)
                credits.extend(c2)
        except Exception:
            pass
    return paths, credits


def fetch_videos_parallel(
    queries: list[str],
    out_dir: Path,
    *,
    orientation: str = "landscape",
    max_workers: int = 4,
    brief: str | None = None,
) -> list[tuple[str, list[Path], list[dict[str, Any]]]]:
    """Download one on-brief clip per query. Never pads with unrelated office stock."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    out_dir.mkdir(parents=True, exist_ok=True)
    brief_text = (brief or " ".join(queries)).strip()
    raw: dict[str, tuple[list[Path], list[dict[str, Any]]]] = {}

    def _one(q: str) -> tuple[str, list[Path], list[dict[str, Any]]]:
        paths, creds = fetch_videos(
            q,
            out_dir,
            count=3,
            orientation=orientation,
            brief=brief_text,
        )
        return q, paths, creds

    with ThreadPoolExecutor(max_workers=max(1, min(6, int(max_workers or 4)))) as pool:
        futs = {pool.submit(_one, q): q for q in queries if q}
        for fut in as_completed(futs):
            q, paths, creds = fut.result()
            raw[q] = (paths, creds)

    used: set[str] = set()
    ordered: list[tuple[str, list[Path], list[dict[str, Any]]]] = []
    for q in queries:
        paths, creds = raw.get(q, ([], []))
        chosen_p: list[Path] = []
        chosen_c: list[dict[str, Any]] = []
        for path, cred in zip(paths, creds):
            key = str(Path(path).resolve())
            if key in used:
                continue
            used.add(key)
            chosen_p.append(path)
            chosen_c.append(cred)
            break
        ordered.append((q, chosen_p, chosen_c))
    return ordered
