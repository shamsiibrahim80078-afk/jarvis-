"""YouTube comment CTA / soft auto-reply helpers."""

from __future__ import annotations

import logging
import re
import time
from typing import Any

logger = logging.getLogger(__name__)

CTA_COMMENT = (
    "If you want the full YT Shorts + clipping automation, comment YT 👇 "
    "Like + follow for daily Shorts."
)


def post_cta_comment(video_id: str, text: str | None = None) -> dict[str, Any]:
    """Post a channel comment on a video (needs youtube.force-ssl scope)."""
    if not video_id:
        return {"ok": False, "message": "No video id"}
    body_text = (text or CTA_COMMENT).strip()[:900]
    try:
        from jarvis.mira.youtube_upload import _load_creds
        from googleapiclient.discovery import build

        creds = _load_creds()
        if not creds:
            return {"ok": False, "message": "YouTube not connected"}
        yt = build("youtube", "v3", credentials=creds)
        yt.commentThreads().insert(
            part="snippet",
            body={
                "snippet": {
                    "videoId": video_id,
                    "topLevelComment": {"snippet": {"textOriginal": body_text}},
                }
            },
        ).execute()
        return {"ok": True, "message": "CTA comment posted."}
    except Exception as exc:
        err = str(exc)
        if "insufficientPermissions" in err or "403" in err:
            return {
                "ok": False,
                "message": (
                    "Comment scope missing — say 'connect youtube' once to re-auth "
                    "(needed for auto CTA comments)."
                ),
            }
        logger.warning("cta comment failed: %s", exc)
        return {"ok": False, "message": f"Comment failed: {err[:160]}"}


def reply_recent_comments(
    video_id: str,
    *,
    max_replies: int = 5,
    reply_text: str = "Thanks! More Shorts daily — follow for Part 2 🔥",
) -> dict[str, Any]:
    """Soft-reply to recent top-level comments (best-effort)."""
    if not video_id:
        return {"ok": False, "message": "No video id"}
    try:
        from jarvis.mira.youtube_upload import _load_creds
        from googleapiclient.discovery import build

        creds = _load_creds()
        if not creds:
            return {"ok": False, "message": "YouTube not connected"}
        yt = build("youtube", "v3", credentials=creds)
        threads = yt.commentThreads().list(
            part="snippet",
            videoId=video_id,
            maxResults=min(20, max(3, int(max_replies) * 2)),
            order="time",
            textFormat="plainText",
        ).execute()
        done = 0
        for th in threads.get("items") or []:
            if done >= max_replies:
                break
            top = ((th.get("snippet") or {}).get("topLevelComment") or {}).get("snippet") or {}
            # Skip our own
            if top.get("authorChannelId", {}).get("value") and False:
                pass
            parent = th["snippet"]["topLevelComment"]["id"]
            text = str(top.get("textDisplay") or top.get("textOriginal") or "")
            # Don't reply to ourselves if CTA already there
            if "comment yt" in text.lower() and "automation" in text.lower():
                continue
            try:
                yt.comments().insert(
                    part="snippet",
                    body={"snippet": {"parentId": parent, "textOriginal": reply_text[:900]}},
                ).execute()
                done += 1
                time.sleep(0.4)
            except Exception:
                continue
        return {"ok": True, "replied": done, "message": f"Replied to {done} comment(s)."}
    except Exception as exc:
        err = str(exc)
        if "insufficientPermissions" in err or "403" in err:
            return {
                "ok": False,
                "message": "Need re-auth for comments. Say: connect youtube",
            }
        return {"ok": False, "message": f"Reply failed: {err[:160]}"}


def is_comment_intent(text: str) -> bool:
    t = (text or "").lower()
    return bool(
        re.search(
            r"\b(reply\s+to\s+comments?|auto\s*reply\s+comments?|"
            r"post\s+cta\s+comment|comment\s+cta)\b",
            t,
        )
    )
