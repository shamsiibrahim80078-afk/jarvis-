"""YouTube Shorts growth helpers — Vugola / clipping-style playbook.

Goal: more Shorts views + subs via vertical clips, hooks, captions, public posts.
"""

from __future__ import annotations

import re
from typing import Any, Callable


def is_growth_post_intent(text: str) -> bool:
    lower = (text or "").lower()
    if not lower:
        return False
    if re.search(r"\b(upload|post)\s+(?:last|this|the)\s+(?:video|short|clip)\b", lower):
        return False
    try:
        from jarvis.mira.clipping import looks_like_clip_command

        if looks_like_clip_command(text):
            return False
    except Exception:
        pass
    try:
        from jarvis.mira.schedule import is_schedule_intent

        if is_schedule_intent(text):
            return False
    except Exception:
        pass
    return bool(
        re.search(
            r"\b(viral|growth|grow|faceless)\b.{0,30}\b(short|shorts|reel|youtube)\b|"
            r"\b(short|shorts|reel)\b.{0,30}\b(viral|growth|grow)\b|"
            r"\b(post|publish|drop)\s+(?:a\s+)?(?:viral\s+|growth\s+)?short\b|"
            r"\bgrowth\s+short\b|"
            r"\bmake\s+(?:me\s+)?(?:a\s+)?(?:viral\s+)?short\s+(?:and\s+)?(?:post|upload|publish)\b|"
            r"\bpost\s+(?:a\s+)?short\s+about\b",
            lower,
        )
    )


def extract_growth_topic(text: str) -> str:
    raw = (text or "").strip()
    lower = raw.lower()
    m = re.search(
        r"(?:short|shorts|reel|video)\s+(?:about|on|of)\s+(.+)$",
        raw,
        re.I,
    )
    if m:
        topic = m.group(1).strip()
    else:
        topic = re.sub(
            r"\b(make|create|generate|post|publish|upload|drop|viral|growth|grow|"
            r"youtube|shorts?|reel|clipping|faceless|and|to|a|an|the|me|please)\b",
            " ",
            lower,
            flags=re.I,
        )
        topic = re.sub(r"\s+", " ", topic).strip(" .,:;-")
    topic = re.sub(r"\s+", " ", topic).strip() or "mind-blowing facts"
    return topic[:120]


def viral_hook_line(topic: str) -> str:
    from jarvis.mira.packaging import viral_hook_line as _hook

    return _hook(topic)


def viral_title_description(topic: str) -> tuple[str, str]:
    from jarvis.mira.packaging import viral_title_description as _pack

    return _pack(topic)


def run_growth_short(
    topic: str,
    *,
    progress_cb: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Generate Short → retention polish → A/B title → publish PUBLIC + CTA comment."""

    def _p(msg: str) -> None:
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    from jarvis.mira.ab_titles import attach_video_id, pick_ab_title
    from jarvis.mira.packaging import pack_short
    from jarvis.mira.pipeline import run_video
    from jarvis.mira.voices import voice_for_mood
    from jarvis.mira.youtube_upload import upload_video

    topic = (topic or "").strip() or "mind-blowing facts"
    pack = pack_short(topic)
    title, _alt, _style = pick_ab_title(topic, pack)
    desc = str(pack["description"])
    hook = str(pack["hook"])
    tags = list(pack.get("tags") or ["shorts", "viral"])
    mood = str(pack.get("mood") or "curious")
    voice = voice_for_mood(mood)

    _p(f"Growth mode: “{topic}” ({mood} / {voice})…")
    # Keep brief = topic so verifier matches stock/VO to the scheduled idea
    out = run_video(
        topic,
        duration_sec=20,
        aspect="9:16",
        audio_mode="voice",
        mood=mood,
        voice=voice,
        script=topic,
        search_hints=[topic, f"{topic} close up", f"{topic} cinematic"],
    )
    if not out.get("ok"):
        return {
            "ok": False,
            "message": out.get("message") or "Could not generate Short for growth.",
        }

    path = out.get("path") or out.get("video_path") or ""
    _p(f"Retention polish + hook “{hook}” + end card…")
    try:
        from jarvis.mira.retention import polish_for_retention

        polished = polish_for_retention(
            path,
            hook=hook,
            end_card="Follow for Part 2",
            label="growth",
        )
        if polished.get("ok") and polished.get("path"):
            path = str(polished["path"])
            try:
                from jarvis.mira.last_output import load_last_output, save_last_output

                last = load_last_output() or {}
                save_last_output({
                    **last,
                    **out,
                    "path": path,
                    "video_path": path,
                    "aspect": "9:16",
                    "format": "youtube_shorts",
                    "topic": topic,
                })
            except Exception:
                pass
    except Exception as exc:
        _p(f"Retention polish skipped ({exc}) — continuing…")

    # Bank a copy in clip library
    try:
        from jarvis.mira.clip_library import add_clip

        if path:
            add_clip(path, topic=topic, tags=tags)
    except Exception:
        pass

    # Multi-platform export folders
    try:
        from jarvis.mira.export_platforms import export_platforms

        if path:
            export_platforms(path)
    except Exception:
        pass

    _p("Publishing PUBLIC Short…")
    up = upload_video(
        path=path or None,
        title=title,
        description=desc,
        tags=tags,
        privacy="public",
        force_shorts=True,
        progress_cb=progress_cb,
    )
    if not up.get("ok"):
        return up

    url = str(up.get("url") or "")
    vid = ""
    m = re.search(r"(?:youtu\.be/|v=)([\w-]{6,})", url)
    if m:
        vid = m.group(1)
    if vid:
        try:
            attach_video_id(vid)
        except Exception:
            pass
        try:
            from jarvis.mira.comments import post_cta_comment

            _p("Posting CTA comment…")
            post_cta_comment(vid)
        except Exception:
            pass

    return {
        "ok": True,
        "url": url,
        "title": up.get("title") or title,
        "path": path,
        "video_id": vid,
        "message": (
            f"Done, sir. Growth Short LIVE: {up.get('title') or title} — {url}"
        ),
    }
