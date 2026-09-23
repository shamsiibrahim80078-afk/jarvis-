"""YouTube Shorts analytics + topic intelligence."""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "data" / "mira" / "analytics.json"


def _load() -> dict[str, Any]:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    if not PATH.is_file():
        return {"videos": {}, "suggestions": [], "updated_at": 0}
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"videos": {}, "suggestions": [], "updated_at": 0}
    except Exception:
        return {"videos": {}, "suggestions": [], "updated_at": 0}


def _save(data: dict[str, Any]) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _youtube():
    from jarvis.mira.youtube_upload import _load_creds
    from googleapiclient.discovery import build

    creds = _load_creds()
    if not creds:
        return None
    return build("youtube", "v3", credentials=creds)


def pull_recent_stats(*, max_results: int = 15) -> dict[str, Any]:
    """Fetch recent uploads stats (views/likes/comments)."""
    yt = _youtube()
    if not yt:
        return {"ok": False, "message": "YouTube not connected. Say: connect youtube"}

    try:
        ch = yt.channels().list(part="contentDetails", mine=True).execute()
        items = ch.get("items") or []
        if not items:
            return {"ok": False, "message": "No YouTube channel found."}
        uploads = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
        pl = yt.playlistItems().list(
            part="contentDetails,snippet",
            playlistId=uploads,
            maxResults=min(25, max(5, int(max_results))),
        ).execute()
        ids = [it["contentDetails"]["videoId"] for it in (pl.get("items") or []) if it.get("contentDetails")]
        if not ids:
            return {"ok": True, "videos": [], "message": "No uploads yet."}

        vids = yt.videos().list(part="snippet,statistics", id=",".join(ids)).execute()
        rows: list[dict[str, Any]] = []
        by_id: dict[str, dict[str, Any]] = {}
        for v in vids.get("items") or []:
            st = v.get("statistics") or {}
            sn = v.get("snippet") or {}
            row = {
                "id": v.get("id"),
                "title": sn.get("title"),
                "views": int(st.get("viewCount") or 0),
                "likes": int(st.get("likeCount") or 0),
                "comments": int(st.get("commentCount") or 0),
                "published_at": sn.get("publishedAt"),
            }
            rows.append(row)
            by_id[str(v.get("id"))] = row

        rows.sort(key=lambda r: r["views"], reverse=True)
        data = _load()
        data["videos"] = {**(data.get("videos") or {}), **by_id}
        data["updated_at"] = time.time()
        data["top"] = rows[:5]
        _save(data)

        # Feed A/B winner learning
        try:
            from jarvis.mira.ab_titles import mark_winner_from_stats

            ab_msg = mark_winner_from_stats(by_id)
        except Exception:
            ab_msg = ""

        suggestions = suggest_topics_from_top(rows[:5])
        data["suggestions"] = suggestions
        _save(data)

        lines = [f"• {r['title'][:50]} — {r['views']} views" for r in rows[:5]]
        msg = "Top Shorts:\n" + ("\n".join(lines) if lines else "(none)")
        if suggestions:
            msg += "\nSuggested next topics: " + ", ".join(suggestions[:5])
        if ab_msg:
            msg += f"\n{ab_msg}"
        return {"ok": True, "videos": rows, "suggestions": suggestions, "message": msg}
    except Exception as exc:
        logger.warning("analytics pull failed: %s", exc)
        return {"ok": False, "message": f"Analytics failed: {str(exc)[:180]}"}


def suggest_topics_from_top(top_rows: list[dict[str, Any]]) -> list[str]:
    """Expand winning titles into related topic ideas."""
    seeds: list[str] = []
    for r in top_rows or []:
        title = re.sub(r"#\w+", "", str(r.get("title") or ""))
        title = re.sub(
            r"\b(you won't believe this|wait for it|nobody talks about|pov|gone wrong|save this)\b",
            " ",
            title,
            flags=re.I,
        )
        title = re.sub(r"\s+", " ", title).strip(" .,:;-")
        if title and len(title) > 3:
            seeds.append(title[:80])

    out: list[str] = []
    for s in seeds[:4]:
        out.append(s)
        out.append(f"{s} tips")
        out.append(f"facts about {s}")
    # LLM expand if available
    try:
        from jarvis.mira.director import _llm_json

        planned = _llm_json(
            'Return ONLY JSON: {"topics":["...", "..."]} — 5 related Shorts topics, same niche.',
            f"Winning titles/topics: {seeds[:5]}",
            timeout=8.0,
        )
        if isinstance(planned, dict):
            for t in planned.get("topics") or []:
                t = re.sub(r"\s+", " ", str(t)).strip()
                if t and t.lower() not in {x.lower() for x in out}:
                    out.append(t[:80])
    except Exception:
        pass

    # dedupe
    seen: set[str] = set()
    uniq: list[str] = []
    for t in out:
        k = t.lower()
        if k not in seen:
            seen.add(k)
            uniq.append(t)
    return uniq[:12]


def apply_suggestions_to_schedule(*, limit: int = 5) -> str:
    data = _load()
    suggestions = list(data.get("suggestions") or [])
    if not suggestions:
        pull = pull_recent_stats()
        if not pull.get("ok"):
            return pull.get("message") or "Could not pull analytics."
        suggestions = list(pull.get("suggestions") or [])
    if not suggestions:
        return "No suggestions yet — post a few Shorts first, then say: grow my topics"
    from jarvis.mira.schedule import add_topics

    return add_topics(suggestions[: max(1, min(10, int(limit)))])


def is_analytics_intent(text: str) -> bool:
    t = (text or "").lower()
    return bool(
        re.search(
            r"\b(youtube\s+analytics|shorts?\s+analytics|pull\s+analytics|"
            r"how\s+are\s+my\s+shorts|my\s+shorts?\s+(views|stats)|"
            r"grow\s+my\s+topics|suggest\s+topics|topic\s+intelligence)\b",
            t,
        )
    )


def parse_analytics_command(text: str) -> dict[str, Any] | None:
    if not is_analytics_intent(text):
        return None
    lower = (text or "").lower()
    if re.search(r"\b(grow\s+my\s+topics|suggest\s+topics|add\s+winning\s+topics)\b", lower):
        return {"action": "analytics_grow_topics"}
    return {"action": "analytics_pull"}
