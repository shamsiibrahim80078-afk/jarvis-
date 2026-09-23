"""Mira tools — generate images/videos and rate quality for learning."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

from jarvis.mira.model import generate

ROOT = Path(__file__).resolve().parents[2]
MIRA_BASE = "http://127.0.0.1:8765"


def media_url_for_path(path: str | Path | None) -> str | None:
    """Map a local Mira file to a localhost URL for Chrome playback."""
    if not path:
        return None
    p = Path(path)
    try:
        rel = p.resolve().relative_to((ROOT / "data" / "mira").resolve())
    except ValueError:
        # Allow absolute under data/mira even if resolve differs
        s = str(p).replace("\\", "/")
        m = re.search(r"/data/mira/(videos|images)/([^/]+)$", s, re.I)
        if not m:
            return None
        return f"{MIRA_BASE}/mira/media/{m.group(1)}/{quote(m.group(2))}"
    parts = rel.parts
    if len(parts) < 2:
        return None
    kind, name = parts[0], parts[-1]
    if kind not in ("videos", "images"):
        return None
    return f"{MIRA_BASE}/mira/media/{kind}/{quote(name)}"


def open_mira_media_in_chrome(path: str = "", *, media_url: str | None = None) -> str:
    """Open generated Mira media in a new Chrome tab (preferred) or default player."""
    url = media_url or media_url_for_path(path)
    if url:
        try:
            from jarvis.tools.system import open_in_chrome

            open_in_chrome(url, new_window=False)
            return url
        except Exception:
            pass
    if path and Path(path).is_file():
        try:
            import os

            os.startfile(str(path))  # noqa: S606
        except Exception:
            pass
    return url or path or ""


def _open_path(path: str) -> None:
    open_mira_media_in_chrome(path)


def create_image(topic: str = "", style: str = "cinematic") -> str:
    topic = (topic or "").strip()
    if not topic:
        return "Need a topic for the image, sir."
    out = generate("create_image", topic=topic, style=style or "cinematic")
    if not out.get("ok"):
        return out.get("message") or "Image generation failed."
    path = out.get("image_path") or ""
    url = open_mira_media_in_chrome(path) if path else ""
    if url and url.startswith("http"):
        return f"Image ready via Mira — opened in Chrome: {url}"
    return f"Image ready via Mira: {path}"


def create_video(
    topic: str = "",
    duration_sec: str = "30",
    aspect: str = "16:9",
    script: str = "",
    audio_mode: str = "voice",
    media_paths: str = "",
    use_uploads: str = "",
    search_hints: str = "",
    force_character: str = "",
    mood: str = "",
    format_key: str = "",
    fit_mode: str = "",
) -> str:
    topic = (topic or "").strip()
    if not topic:
        return "Need a topic for the video, sir."
    try:
        dur = int(str(duration_sec or "30").strip() or "30")
    except ValueError:
        dur = 30
    paths: list[str] = []
    raw_paths = (media_paths or "").strip()
    if raw_paths:
        for part in re.split(r"[|,\n;]+", raw_paths):
            p = part.strip().strip('"').strip("'")
            if p:
                paths.append(p)
    use_up = str(use_uploads or "").strip().lower() in ("1", "true", "yes", "y", "on")
    hints: list[str] = []
    if (search_hints or "").strip():
        for part in re.split(r"[|,\n;]+", search_hints):
            h = part.strip()
            if h:
                hints.append(h)
    force_char = str(force_character or "").strip().lower() in ("1", "true", "yes", "y", "on")
    fit = (fit_mode or "").strip().lower()
    # Apply platform format preset if given
    try:
        from jarvis.mira.formats import apply_format

        applied = apply_format(format_key or None, aspect=aspect or "16:9", duration_sec=dur)
        aspect = applied["aspect"]
        dur = int(applied["duration_sec"])
        fmt_label = applied.get("format_label") or ""
    except Exception:
        fmt_label = ""
    out = generate(
        "create_video",
        topic=topic,
        duration_sec=dur,
        aspect=aspect or "16:9",
        script=script or None,
        audio_mode=audio_mode or "voice",
        media_paths=paths or None,
        use_uploads=use_up,
        search_hints=hints or None,
        force_character=force_char,
        mood=(mood or "").strip() or None,
        fit_mode=fit or ("contain" if use_up or paths else None),
    )
    if not out.get("ok"):
        return out.get("message") or "Video generation failed."
    path = out.get("video_path") or ""
    # On-screen text = exact topic (never invent a different viral hook)
    if path and str(aspect or "").strip() in ("9:16", "9x16") and topic and not (use_up or paths):
        try:
            from jarvis.mira.edit import edit_video

            hook = re.sub(r"\s+", " ", (topic or "").strip())[:36]
            if hook:
                edited = edit_video(
                    source=path,
                    aspect="9:16",
                    text=hook,
                    label="topic",
                )
                if edited.get("ok") and edited.get("path"):
                    path = str(edited["path"])
                    out["video_path"] = path
                    out["path"] = path
                    try:
                        from jarvis.mira.last_output import load_last_output, save_last_output

                        last = load_last_output() or {}
                        save_last_output({**last, **out, "path": path, "video_path": path})
                    except Exception:
                        pass
        except Exception:
            pass
    url = open_mira_media_in_chrome(path) if path else ""
    extra = f" ({fmt_label})" if fmt_label else ""
    mood_s = f" · {mood}" if (mood or "").strip() else ""
    if url and url.startswith("http"):
        return (
            f"Video ready via Mira{extra}{mood_s} — opened in a new Chrome tab: {url}. "
            "Rate it 1–5 (say 'rate this video 5') so quality improves."
        )
    return (
        f"Video ready via Mira{extra}{mood_s}: {path}. "
        "Rate it 1–5 (say 'rate this video 5') so quality improves."
    )


def edit_last_video(
    aspect: str = "",
    duration_sec: str = "",
    start_sec: str = "",
    speed: str = "",
    mute: str = "",
    volume: str = "",
    text: str = "",
    label: str = "edit",
) -> str:
    from jarvis.mira.edit import edit_video

    def _f(v: str) -> float | None:
        if not str(v or "").strip():
            return None
        try:
            return float(str(v).strip())
        except ValueError:
            return None

    out = edit_video(
        aspect=(aspect or None) or None,
        duration_sec=_f(duration_sec),
        start_sec=_f(start_sec) or 0.0,
        speed=_f(speed),
        mute=str(mute or "").strip().lower() in ("1", "true", "yes", "y", "on", "mute"),
        volume=_f(volume),
        text=(text or "").strip() or None,
        label=label or "edit",
    )
    if not out.get("ok"):
        return out.get("message") or "Edit failed."
    path = out.get("video_path") or ""
    try:
        from jarvis.mira.last_output import load_last_output, save_last_output

        last = load_last_output() or {}
        save_last_output({**last, "video_path": path, "aspect": out.get("aspect")})
    except Exception:
        pass
    url = open_mira_media_in_chrome(path) if path else ""
    if url and str(url).startswith("http"):
        return f"{out.get('message')} Opened: {url}"
    return out.get("message") or f"Edited: {path}"


def youtube_connect() -> str:
    from jarvis.mira.youtube_upload import connect

    return connect()


def youtube_status() -> str:
    from jarvis.mira.youtube_upload import status

    return status()


def youtube_upload_last(
    title: str = "",
    privacy: str = "public",
    description: str = "",
    force_shorts: str = "true",
) -> str:
    from jarvis.mira.youtube_upload import upload_video

    def _progress(msg: str) -> None:
        try:
            from jarvis.tools.mira_jobs import set_progress

            set_progress(msg)
        except Exception:
            pass

    force = str(force_shorts or "true").strip().lower() not in ("0", "false", "no", "off")
    out = upload_video(
        title=title or "",
        privacy=privacy or "public",
        description=description or "",
        progress_cb=_progress,
        force_shorts=force,
    )
    if not out.get("ok"):
        return out.get("message") or "YouTube upload failed."
    return out.get("message") or f"Done, sir. Uploaded: {out.get('url') or ''}"


def youtube_upload_ask(privacy: str = "public", title: str = "") -> str:
    from jarvis.mira.youtube_upload import begin_upload_flow

    return begin_upload_flow(privacy=privacy or "public", title=title or "")


def rate_media(rating: str = "4", topic: str = "", note: str = "") -> str:
    try:
        score = int(str(rating or "4").strip() or "4")
    except ValueError:
        score = 4
    out = generate("rate", topic=topic, rating=score, note=note)
    return out.get("message") or "Rating saved."


def mira_status() -> str:
    out = generate("status")
    ident = out if isinstance(out, dict) else {}
    return (
        f"{ident.get('mira_model', 'Mira')} ({ident.get('model_id')}). "
        f"Rated examples: {ident.get('rated_examples', 0)}. "
        f"Output: {ident.get('out_dir')}"
    )


def is_mira_followup_intent(text: str) -> bool:
    """Format/mood reply while pending, or edit/crop of last video."""
    lower = (text or "").lower().strip()
    if not lower:
        return False
    try:
        from jarvis.mira.growth import is_growth_post_intent

        if is_growth_post_intent(text):
            return True
    except Exception:
        pass
    if re.search(r"\b(cancel|never\s*mind|forget\s+it)\b", lower):
        try:
            from jarvis.mira.session import load_pending

            if load_pending():
                return True
        except Exception:
            pass
    try:
        from jarvis.mira.edit import is_edit_intent

        if is_edit_intent(text):
            return True
    except Exception:
        pass
    try:
        from jarvis.mira.youtube_upload import (
            is_youtube_connect_intent,
            is_youtube_upload_intent,
            load_pending_upload,
            parse_caption_reply,
        )

        if is_youtube_connect_intent(text) or is_youtube_upload_intent(text):
            return True
        if load_pending_upload() and parse_caption_reply(text) is not None:
            return True
    except Exception:
        pass
    try:
        from jarvis.mira.formats import looks_like_new_brief, parse_format_reply
        from jarvis.mira.session import load_pending

        pending = load_pending()
        if pending and looks_like_new_brief(text):
            return True  # New idea — Mira generate owns it
        if pending and parse_format_reply(text):
            return True
        # Numbered menu reply while pending
        if pending and re.match(r"^[\s#]*[1-6]\b", lower):
            return True
    except Exception:
        pass
    return False


def is_youtube_watch_intent(text: str) -> bool:
    """True when user wants YouTube search/play — not AI generate or upload."""
    lower = (text or "").lower()
    if re.search(r"\b(upload|post|publish|connect|authorize)\b", lower) and "youtube" in lower:
        return False
    if "youtube" in lower or "on yt" in lower:
        # Generating a youtube *format* is Mira, not search
        if re.search(r"\b(make|create|generate|render|produce|shoot)\b", lower):
            return False
        if re.search(r"\b(shorts?|video)\b", lower) and re.search(
            r"\b(about|of|for|with)\b", lower
        ):
            return False
        return True
    if re.search(r"\b(search|find|play|look\s*up)\b.{0,40}\b(video|clip)\b", lower):
        if not re.search(r"\b(make|create|generate|render|produce)\b", lower):
            return True
    return False


def is_mira_generate_intent(text: str) -> bool:
    """Open intent — ANY creative ask. Not a fixed prompt list / trained whitelist."""
    if is_youtube_watch_intent(text):
        return False
    lower = (text or "").lower().strip()
    if not lower:
        return False
    if re.search(r"\b(mira\s+status|status\s+of\s+mira)\b", lower):
        return True
    if re.search(r"(?:mira\s+)?rate\s+(?:this\s+)?(?:video|image|media)?\s*[1-5]\b", lower):
        return True
    if re.search(r"\bmira_rate\s+[1-5]\b", lower):
        return True
    try:
        from jarvis.mira.office_routine import is_office_routine_request

        if is_office_routine_request(lower):
            return True
    except Exception:
        pass
    try:
        from jarvis.mira.uploads import wants_user_media

        if wants_user_media(lower) and re.search(
            r"\b(video|clip|reel|montage|edit|film|movie|picture|photo|image)\b",
            lower,
        ):
            return True
    except Exception:
        pass

    # Broad generate verbs + media nouns (order flexible)
    gen = (
        r"(make|create|generate|render|produce|shoot|edit|build|craft|compose|turn|convert|"
        r"film|show\s+me|put\s+together|whip\s+up|cook\s+up|do\s+me|gimme|give\s+me|"
        r"do\s+that|do\s+something)"
    )
    media = (
        r"(video|clip|reel|short|shorts|film|movie|montage|image|picture|photo|still|"
        r"footage|animation|content)"
    )
    if re.search(rf"\b{gen}\b.{{0,80}}\b(an?\s+)?(ai\s+)?{media}\b", lower):
        return True
    if re.search(rf"\b(an?\s+)?(ai\s+)?{media}\b.{{0,60}}\b{gen}\b", lower):
        return True
    # Screen-record / platform tour phrasing (no "create" verb required)
    if re.search(
        r"\b(screen\s*record|record\s+(?:the\s+)?(?:live\s+)?(?:site|page|platform|screen)|"
        r"full\s+(?:platform\s+)?(?:video|tour)|platform\s+tour|walk\s*through|"
        r"quick\s+teaser|teaser\s+of|short\s+tour|preview\s+of)\b",
        lower,
    ):
        return True
    try:
        from jarvis.mira.platforms import detect_platform

        if detect_platform(lower) and re.search(
            r"\b(video|clip|tour|record|mira|walkthrough|walk\s*through|teaser|preview|short)\b",
            lower,
        ):
            return True
    except Exception:
        pass
    # Natural speech: I want / need / can you / please + video about…
    if re.search(
        rf"\b(i\s+want|i\s+need|i'?d\s+like|can\s+(?:you|u)|could\s+(?:you|u)|please|pls|wanna|want\s+you\s+to)\b"
        rf".{{0,60}}\b(an?\s+)?(ai\s+)?{media}\b",
        lower,
    ):
        return True
    if re.search(rf"\b(ai\s+)?{media}\b.{{0,30}}\b(about|of|on|for|from|with)\b", lower) and re.search(
        r"\b(make|create|generate|render|want|need|like|please|edit|from|using|show|gimme)\b",
        lower,
    ):
        return True
    # Casual: "show me dogs on a beach", "do something about pasta cooking"
    if re.search(
        r"\b(show\s+me|do\s+(?:me\s+)?(?:a\s+)?(?:something|one|that)|"
        r"put\s+together|whip\s+up|i\s+need\s+something|something\s+(?:cool|nice|about)|"
        r"can\s+(?:you|u)\s+do)\b",
        lower,
    ) and (
        re.search(rf"\b{media}\b", lower)
        or re.search(r"\b(about|with|of|showing)\b.{0,60}[a-z]{3,}", lower)
        or re.search(
            r"\b(dog|dogs|cat|cats|beach|pasta|tokyo|fruit|fruits|scuba|mountain|"
            r"snow|rain|city|ocean|sunset|cooking|diving)\b",
            lower,
        )
    ):
        return True
    # Dialogue / talking subjects even without "video"
    if re.search(r"\b(talk|talking|speak|speaking|argue|arguing)\b", lower) and re.search(
        r"\b(fruit|fruits|cat|cats|dog|dogs|animal|toy|robot|dragon|character)\b",
        lower,
    ):
        return True
    if "mira" in lower and (
        re.search(rf"\b{media}\b", lower)
        or re.search(
            r"\b(about|make|create|generate|show|do)\b",
            lower,
        )
    ):
        return True
    # Fast heuristic only (no LLM here — keep routing snappy)
    try:
        from jarvis.mira.understand import _heuristic_understand

        u = _heuristic_understand(text)
        if u.get("wants_media") and float(u.get("confidence") or 0) >= 0.65:
            return True
    except Exception:
        pass
    return False


def _clean_topic(topic: str) -> str:
    """Keep the user's full creative brief — only strip command chrome, not ideas."""
    t = (topic or "").strip()
    # Prefer GPT-style normalizer when available
    try:
        from jarvis.mira.understand import _heuristic_understand

        u = _heuristic_understand(t)
        brief = str(u.get("brief") or "").strip()
        if brief and len(brief) >= 3:
            # Still strip residual chrome below
            t = brief
    except Exception:
        pass
    # Remove leading command phrases; keep everything after (the real prompt)
    t = re.sub(
        r"^(?:mira[,:]?\s*)?(?:please\s+)?(?:can\s+you\s+|could\s+you\s+)?"
        r"(?:i\s+(?:want|need)\s+(?:you\s+to\s+)?|i'?d\s+like\s+(?:you\s+to\s+)?|wanna\s+)?"
        r"(?:to\s+)?"
        r"(?:create|make|generate|render|produce|shoot|edit|build|craft|compose|turn(?:\s+\w+)?\s+into|"
        r"show\s+me|put\s+together|whip\s+up|gimme|give\s+me|do\s+me)\s+"
        r"(?:me\s+)?(?:an?\s+)?(?:ai\s+)?(?:video|clip|reel|short|shorts|film|movie|montage|"
        r"image|picture|photo|still|thing|something|one)?\s*"
        r"(?:about|on|of|for|from|with|showing|featuring)?\s*",
        "",
        t,
        count=1,
        flags=re.I,
    )
    # Residual: "I want a video of …" when verb was only "want"
    t = re.sub(
        r"^(?:i\s+(?:want|need)|i'?d\s+like|wanna)\s+(?:an?\s+)?(?:ai\s+)?"
        r"(?:video|clip|reel|film|movie|montage|image|picture|photo)\s*"
        r"(?:about|on|of|for|from|with)?\s*",
        "",
        t,
        count=1,
        flags=re.I,
    )
    t = re.sub(
        r"^edit\s+my\s+(?:uploads?|videos?|clips?|images?|photos?|pictures?|media)\s+"
        r"(?:into\s+)?(?:an?\s+)?(?:video|clip|reel|montage)?\s*",
        "",
        t,
        count=1,
        flags=re.I,
    )
    t = re.sub(r"\b(?:rate\s+this|mira_rate)\b.*$", "", t, flags=re.I)
    t = re.sub(r"\b\d+\s*(?:s|sec|secs|second|seconds)\b", "", t, flags=re.I)
    # Chained second command: "… morning create an image of a desk" → keep first brief only
    t = re.sub(
        r"\s+(?:and\s+)?(?:then\s+)?(?:create|make|generate|render|produce|build)\s+"
        r"(?:me\s+)?(?:an?\s+)?(?:ai\s+)?"
        r"(?:image|picture|photo|still|video|clip|reel|short|shorts|film|movie|montage)\b.*$",
        "",
        t,
        flags=re.I,
    )
    # Aspect only in command form — do NOT strip bare word "short" (destroys briefs)
    t = re.sub(r"\b(?:vertical\s+video|as\s+a\s+short|youtube\s+shorts?|9\s*:\s*16|16\s*:\s*9)\b", "", t, flags=re.I)
    # Strip upload/growth chrome so brief stays EXACTLY the creative ask
    t = re.sub(
        r"\b(?:and\s+)?(?:then\s+)?(?:upload|post|publish|share)\s+(?:it\s+|this\s+|them\s+)?"
        r"(?:to\s+)?(?:youtube(?:\s+shorts?)?|yt|shorts?|tiktok|reels?)?\b",
        " ",
        t,
        flags=re.I,
    )
    t = re.sub(
        r"\b(?:viral|growth|grow|clipping|faceless|for\s+(?:views?|subs?|subscribers?|money|earning))\b",
        " ",
        t,
        flags=re.I,
    )
    t = re.sub(r"\b(?:with|using|via)\s+mira\b", "", t, flags=re.I)
    t = re.sub(
        r"\b(?:using|with|from)\s+my\s+uploads?\b",
        "",
        t,
        flags=re.I,
    )
    t = re.sub(
        r"\b(?:no\s+voice|without\s+narration|ambient(?:\s+only)?|background\s+sound|"
        r"\bmute\b|\bsilent\b|no\s+audio|no\s+sound|music\s+only|with\s+music|bgm)\b",
        "",
        t,
        flags=re.I,
    )
    t = re.sub(r"^mira\s+", "", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip(" .,:;-")
    # Drop leftover "about" if chrome left "mute about X" → "about X"
    t = re.sub(r"^(?:about|on|of|for)\s+", "", t, flags=re.I).strip() or t
    return t


def _detect_audio_mode(text: str) -> str:
    """voice (default) | ambient (scene sound, no VO) | both | mute."""
    lower = (text or "").lower()
    if re.search(
        r"\b(both|voice\s+and\s+ambient|vo\s*\+\s*ambient|narration\s+and\s+(?:bg|background|ambient))\b",
        lower,
    ):
        return "both"
    if re.search(r"\b(mute|silent|no\s+audio|no\s+sound)\b", lower):
        return "mute"
    if re.search(
        r"\b(no\s+(?:voice|vo|narration|listening|speech)|without\s+(?:voice|narration|vo)|"
        r"ambient(?:\s+only)?|background\s+(?:sound|audio|noise)|scene\s+audio|"
        r"just\s+(?:music|sound|ambient)|with\s+music|music\s+only|bgm)\b",
        lower,
    ):
        return "ambient"
    # lipsync / listening → still VO for now (true lip-sync is a later engine)
    return "voice"


def create_office_day(
    day: str = "",
    duration_sec: str = "45",
    aspect: str = "16:9",
    language: str = "en",
    audio_mode: str = "voice",
) -> str:
    from jarvis.mira.office_routine import current_episode_day, generate_office_episode

    ep = None
    if str(day).strip().isdigit():
        ep = int(str(day).strip())
    try:
        dur = int(str(duration_sec or "45").strip() or "45")
    except ValueError:
        dur = 45
    # Default 16:9 1080p — matches gold reference quality
    asp = (aspect or "16:9").strip() or "16:9"
    lang = (language or "en").strip() or "en"
    am = (audio_mode or "voice").strip() or "voice"
    out = generate_office_episode(
        ep or current_episode_day(),
        duration_sec=dur,
        aspect=asp,
        language=lang,
        audio_mode=am,
    )
    if not out.get("ok"):
        return out.get("message") or "Office episode failed."
    path = out.get("video_path") or ""
    url = ""
    if path:
        url = open_mira_media_in_chrome(path)
    msg = out.get("message") or f"Office Day {out.get('episode_day')} ready."
    if url and str(url).startswith("http"):
        return f"{msg} Opened: {url}"
    return msg


def parse_mira_command(text: str) -> dict[str, Any] | None:
    """Natural language → mira action. 'make a video about X' works without saying mira."""
    raw = (text or "").strip()
    lower = raw.lower()
    if not lower:
        return None

    if re.search(r"\b(mira\s+status|status\s+of\s+mira)\b", lower):
        return {"action": "status"}

    rate_m = re.search(
        r"(?:mira\s+)?rate\s+(?:this\s+)?(?:video|image|media)?\s*([1-5])\b",
        lower,
    ) or re.search(r"\bmira_rate\s+([1-5])\b", lower)
    if rate_m:
        return {"action": "rate", "rating": rate_m.group(1), "topic": ""}

    # Office 9–5 series (before generic video parse)
    try:
        from jarvis.mira.office_routine import is_office_routine_request, parse_episode_day

        if is_office_routine_request(raw) or (
            re.search(
                r"\b(make|create|generate)\b.{0,40}\boffice\s+(day|routine|series|vlog|episode)\b",
                lower,
            )
            and re.search(r"\b(day|routine|video|episode|9\s*-?\s*to\s*-?\s*5)\b", lower)
        ):
            day = parse_episode_day(raw) or 0
            # Gold quality default = 16:9 1080p; say reel/vertical/9:16 for shorts
            if any(k in lower for k in ("short", "shorts", "vertical", "9:16", "reel", "tiktok")):
                aspect = "9:16"
            else:
                aspect = "16:9"
            dur = "45"
            dm = re.search(r"(\d+)\s*(?:s|sec|secs|seconds)", lower)
            if dm:
                dur = dm.group(1)
            lang = "en"
            try:
                from jarvis.mira.i18n import detect_lang_from_request

                detected = detect_lang_from_request(raw)
                if detected:
                    lang = detected
            except Exception:
                pass
            return {
                "action": "office_day",
                "day": str(day) if day else "",
                "duration_sec": dur,
                "aspect": aspect,
                "language": lang,
                "audio_mode": _detect_audio_mode(raw),
            }
    except Exception:
        pass

    if not is_mira_generate_intent(raw):
        return None

    # GPT-style: understand ANY messy phrasing → clean brief (not a prompt whitelist)
    understood: dict[str, Any] = {}
    try:
        from jarvis.mira.understand import understand_ask

        understood = understand_ask(raw)
    except Exception:
        understood = {}

    want_image = bool(
        re.search(
            r"\b(make|create|generate|render|produce|shoot|edit|build)\b.{0,80}\b"
            r"(an?\s+)?(ai\s+)?(image|picture|photo|still)\b",
            lower,
        )
    ) or bool(
        re.search(
            r"\b(i\s+want|i\s+need|i'?d\s+like|can\s+you|please).{0,60}\b"
            r"(an?\s+)?(ai\s+)?(image|picture|photo)\b",
            lower,
        )
    ) or (understood.get("media") == "image")
    want_video = bool(
        re.search(
            r"\b(make|create|generate|render|produce|shoot|edit|build|craft|compose|turn|convert|"
            r"show\s+me|put\s+together|whip\s+up|gimme|give\s+me|do\s+me)\b"
            r".{0,80}\b(an?\s+)?(ai\s+)?(video|clip|reel|short|shorts|film|movie|montage)\b",
            lower,
        )
    ) or bool(
        re.search(
            r"\b(i\s+want|i\s+need|i'?d\s+like|can\s+you|could\s+you|please|wanna).{0,60}\b"
            r"(an?\s+)?(ai\s+)?(video|clip|reel|film|movie|montage)\b",
            lower,
        )
    ) or (understood.get("media") == "video" and understood.get("wants_media"))
    # If both in one blob, prefer the first occurrence
    if want_image and want_video:
        img_at = re.search(r"\b(image|picture|photo|still)\b", lower)
        vid_at = re.search(r"\b(video|clip|reel|shorts?|film|movie|montage)\b", lower)
        if img_at and vid_at and img_at.start() < vid_at.start():
            want_video = False
        else:
            want_image = False
    if not want_image and not want_video:
        # Open fallback: any media noun + generate-ish intent already passed is_mira_generate_intent
        want_video = bool(
            re.search(r"\b(video|clip|reel|shorts?|film|movie|montage)\b", lower)
        )
        want_image = (
            bool(re.search(r"\b(image|picture|photo|still)\b", lower)) and not want_video
        )
        if not want_image and not want_video:
            want_video = True  # default Mira generate → video

    # Prefer understood brief (handles slang); fall back to chrome-strip
    topic_clean = str(understood.get("brief") or "").strip() or _clean_topic(raw) or "cinematic scene"
    if len(topic_clean) < 8 and len(_clean_topic(raw) or "") > len(topic_clean):
        topic_clean = _clean_topic(raw)

    # Named platforms OR any web product/SaaS/API → live screen tour (never Shorts stock defaults)
    platform_tour = False
    video_pipeline = "creative_generative"
    try:
        from jarvis.mira.video_router import route_video_ask

        _route = route_video_ask(raw, topic_clean)
        platform_tour = bool(_route.prefer_platform_record)
        video_pipeline = str(_route.pipeline)
    except Exception:
        platform_tour = False
        video_pipeline = "creative_generative"

    from jarvis.mira.formats import apply_format, detect_format, detect_mood

    fmt = detect_format(raw)
    mood = detect_mood(raw)
    if platform_tour:
        applied = apply_format(
            "youtube",
            aspect="16:9",
            duration_sec=max(90, int(understood.get("duration_sec") or 120)),
        )
    else:
        applied = apply_format(
            fmt or "youtube_shorts",  # growth default: Shorts first
            aspect=str(
                understood.get("aspect")
                or ("16:9" if fmt == "youtube" else "9:16")
            ),
            duration_sec=understood.get("duration_sec") or (28 if fmt == "youtube" else 20),
        )
    aspect = applied["aspect"]
    dur = str(applied["duration_sec"])
    dm = re.search(r"(\d+)\s*(?:s|sec|secs|seconds)", lower)
    if dm and (fmt == "youtube" or platform_tour):
        # Explicit seconds for long-form / platform tours
        dur = dm.group(1)

    # Strip format/mood chrome from creative brief
    for alias_group in (
        r"youtube\s+shorts?",
        r"instagram\s+reels?",
        r"instagram\s+stories?",
        r"facebook\s+reels?",
        r"\breels?\b",
        r"\bstories?\b",
        r"\btiktok\b",
        r"\bshorts?\b",
        r"funny|hilarious|sad|angry|epic|calm|romantic|scary|motivational",
        r"mute|silent|no\s+audio|no\s+sound|no\s+voice|ambient(?:\s+only)?|music\s+only|bgm",
    ):
        topic_clean = re.sub(rf"\b{alias_group}\b", " ", topic_clean, flags=re.I)
    topic_clean = re.sub(r"\s+", " ", topic_clean).strip(" .,:;-") or topic_clean
    topic_clean = re.sub(r"^(?:about|on|of|for)\s+", "", topic_clean, flags=re.I).strip() or topic_clean

    use_uploads = bool(understood.get("use_uploads"))
    media_paths: list[str] = []
    try:
        from jarvis.mira.uploads import should_use_uploads, wants_user_media, has_uploads

        from jarvis.tools.command_parse import extract_windows_paths

        use_uploads = bool(understood.get("use_uploads")) or should_use_uploads(raw)
        for wp in extract_windows_paths(raw):
            if re.search(r"\.(mp4|mov|webm|mkv|avi|m4v|jpe?g|png|webp|bmp)\b", wp, re.I):
                media_paths.append(wp)
        from jarvis.mira.uploads import wants_stock_only

        if wants_stock_only(raw):
            use_uploads = False
            media_paths = []
        elif media_paths:
            use_uploads = True
        elif wants_user_media(raw):
            use_uploads = True
        else:
            use_uploads = should_use_uploads(raw)
    except Exception:
        pass

    for wp in media_paths:
        topic_clean = topic_clean.replace(wp, " ")
    topic_clean = _clean_topic(topic_clean) or topic_clean or "my video"

    audio_mode = str(understood.get("audio_mode") or _detect_audio_mode(raw))
    if audio_mode not in ("voice", "ambient", "both", "mute"):
        audio_mode = _detect_audio_mode(raw)

    search_hints = understood.get("search_queries") if isinstance(understood.get("search_queries"), list) else []

    if want_image:
        return {"action": "image", "topic": topic_clean}
    out_format = "youtube" if platform_tour else (fmt or "youtube_shorts")
    parsed: dict[str, Any] = {
        "action": "video",
        "topic": topic_clean,
        "script": topic_clean,
        "duration_sec": dur,
        "aspect": aspect,
        "audio_mode": audio_mode,
        "character_dialogue": bool(understood.get("character_dialogue")),
        "search_hints": [str(q) for q in search_hints if str(q).strip()][:6],
        "understood_via": understood.get("_via"),
        "format": out_format,
        "format_label": applied.get("format_label"),
        "mood": mood,
        "needs_format": False,  # Shorts-first default — no menu delay
        "platform_tour": bool(platform_tour),
        "video_pipeline": video_pipeline,
    }
    if use_uploads:
        parsed["use_uploads"] = True
    if media_paths:
        parsed["media_paths"] = media_paths
    return parsed


def run_parsed_action(parsed: dict[str, Any]) -> str:
    action = parsed.get("action")
    if action == "status":
        return mira_status()
    if action == "rate":
        return rate_media(
            rating=str(parsed.get("rating") or "4"),
            topic=str(parsed.get("topic") or ""),
        )
    if action == "office_day":
        return create_office_day(
            day=str(parsed.get("day") or ""),
            duration_sec=str(parsed.get("duration_sec") or "45"),
            aspect=str(parsed.get("aspect") or "16:9"),
            language=str(parsed.get("language") or "en"),
            audio_mode=str(parsed.get("audio_mode") or "voice"),
        )
    if action == "image":
        return create_image(topic=str(parsed.get("topic") or ""))
    if action == "edit":
        return edit_last_video(
            aspect=str(parsed.get("aspect") or ""),
            duration_sec=str(parsed.get("duration_sec") or ""),
            start_sec=str(parsed.get("start_sec") or ""),
            speed=str(parsed.get("speed") or ""),
            mute="true" if parsed.get("mute") else "",
            volume=str(parsed.get("volume") or ""),
            text=str(parsed.get("text") or ""),
            label=str(parsed.get("label") or "edit"),
        )
    if action == "youtube_connect":
        return youtube_connect()
    if action == "youtube_status":
        return youtube_status()
    if action == "youtube_upload_ask":
        return youtube_upload_ask(
            privacy=str(parsed.get("privacy") or "public"),
            title=str(parsed.get("title") or ""),
        )
    if action == "youtube_upload":
        return youtube_upload_last(
            title=str(parsed.get("title") or ""),
            privacy=str(parsed.get("privacy") or "public"),
            description=str(parsed.get("description") or ""),
            force_shorts="false" if parsed.get("force_shorts") is False else "true",
        )
    if action == "growth_post":
        from jarvis.mira.growth import run_growth_short

        def _progress(msg: str) -> None:
            try:
                from jarvis.tools.mira_jobs import set_progress

                set_progress(msg)
            except Exception:
                pass

        out = run_growth_short(str(parsed.get("topic") or ""), progress_cb=_progress)
        return out.get("message") or "Growth Short finished."
    if action == "clip_shorts":
        from jarvis.mira.clipping import clip_video_to_shorts

        def _clip_prog(msg: str) -> None:
            try:
                from jarvis.tools.mira_jobs import set_progress

                set_progress(msg)
            except Exception:
                pass

        result = clip_video_to_shorts(
            topic_hint=str(parsed.get("topic") or ""),
            max_clips=int(parsed.get("max_clips") or 4),
            upload=bool(parsed.get("upload")),
            privacy=str(parsed.get("privacy") or "public"),
            progress=_clip_prog,
        )
        return result.message
    if action == "schedule_start":
        from jarvis.mira.schedule import start_schedule

        return start_schedule(
            list(parsed.get("topics") or []),
            interval_hours=float(parsed.get("interval_hours") or 3.5),
            post_now=bool(parsed.get("post_now")),
        )
    if action == "schedule_add":
        from jarvis.mira.schedule import add_topics

        return add_topics(list(parsed.get("topics") or []))
    if action == "schedule_stop":
        from jarvis.mira.schedule import stop_schedule

        return stop_schedule()
    if action == "schedule_status":
        from jarvis.mira.schedule import status_message

        hint = parsed.get("_hint")
        if hint:
            return str(hint)
        return status_message()
    if action == "schedule_post_now":
        from jarvis.mira.schedule import force_due_now, run_due_post

        def _sched_prog(msg: str) -> None:
            try:
                from jarvis.tools.mira_jobs import set_progress

                set_progress(msg)
            except Exception:
                pass

        force_due_now()
        out = run_due_post(progress_cb=_sched_prog)
        if out.get("ok"):
            return out.get("message") or "Scheduled Short is live, sir."
        if out.get("skipped"):
            return f"Schedule skipped ({out.get('reason')}). Say: schedule status"
        return out.get("message") or "Scheduled post failed, sir."
    if action == "analytics_pull":
        from jarvis.mira.analytics import pull_recent_stats

        return pull_recent_stats().get("message") or "Analytics done."
    if action == "analytics_grow_topics":
        from jarvis.mira.analytics import apply_suggestions_to_schedule

        return apply_suggestions_to_schedule()
    if action == "export_platforms":
        from jarvis.mira.export_platforms import export_platforms

        return export_platforms().get("message") or "Export done."
    if action == "clip_library_status":
        from jarvis.mira.clip_library import status_message

        return status_message()
    if action == "reply_comments":
        from jarvis.mira.comments import reply_recent_comments
        from jarvis.mira.last_output import load_last_output
        import re as _re

        last = load_last_output() or {}
        url = str(last.get("url") or last.get("youtube_url") or "")
        vid = str(parsed.get("video_id") or "")
        if not vid:
            m = _re.search(r"(?:youtu\.be/|v=)([\w-]{6,})", url)
            vid = m.group(1) if m else ""
        if not vid:
            return "Need a recent uploaded Short video id. Upload one first, sir."
        out = reply_recent_comments(vid)
        return out.get("message") or "Comment replies done."
    if action == "remake":
        from jarvis.mira.formats import apply_format
        from jarvis.mira.last_output import load_last_output

        last = load_last_output() or {}
        # Remake = same topic + new format/mood. Never silently keep uploads from last job.
        topic = str(parsed.get("topic") or last.get("topic") or "").strip()
        if not topic:
            return "No previous video topic to remake. Generate a video first, sir."
        applied = apply_format(
            parsed.get("format"),
            aspect=str(parsed.get("aspect") or last.get("aspect") or "16:9"),
            duration_sec=parsed.get("duration_sec") or last.get("duration_sec") or 30,
        )
        return create_video(
            topic=topic,
            duration_sec=str(applied["duration_sec"]),
            aspect=str(applied["aspect"]),
            script=topic,
            audio_mode=str(last.get("audio_mode") or "voice"),
            mood=str(parsed.get("mood") or last.get("mood") or ""),
            format_key=str(parsed.get("format") or applied.get("format") or ""),
            use_uploads="",  # always fresh stock for remake unless user says uploads
        )
    if action == "video":
        paths = parsed.get("media_paths") or []
        if isinstance(paths, list):
            paths_s = "|".join(str(p) for p in paths)
        else:
            paths_s = str(paths)
        return create_video(
            topic=str(parsed.get("topic") or ""),
            duration_sec=str(parsed.get("duration_sec") or "30"),
            aspect=str(parsed.get("aspect") or "16:9"),
            script=str(parsed.get("script") or parsed.get("topic") or ""),
            audio_mode=str(parsed.get("audio_mode") or "voice"),
            media_paths=paths_s,
            use_uploads="true" if parsed.get("use_uploads") else "",
            search_hints="|".join(str(q) for q in (parsed.get("search_hints") or [])),
            force_character="true" if parsed.get("character_dialogue") else "",
            mood=str(parsed.get("mood") or ""),
            format_key=(
                "youtube"
                if parsed.get("platform_tour")
                else str(parsed.get("format") or "")
            ),
            fit_mode=str(parsed.get("fit_mode") or ""),
        )
    return "Unknown Mira action."


def _visibility_gate(parsed: dict[str, Any]) -> str | None:
    """If uploads would be cropped, pause and ask — never silently cut pixels."""
    if str(parsed.get("action") or "") != "video":
        return None
    if parsed.get("visibility_confirmed"):
        parsed.setdefault("fit_mode", "contain")
        return None
    use_up = bool(parsed.get("use_uploads"))
    paths = parsed.get("media_paths") or []
    if isinstance(paths, str):
        paths = [p for p in re.split(r"[|,\n;]+", paths) if p.strip()]
    if not use_up and not paths:
        return None
    try:
        from jarvis.mira.session import save_pending
        from jarvis.mira.visibility import (
            analyze_upload_visibility,
            resolve_media_for_check,
            visibility_ask_message,
        )

        media = resolve_media_for_check(
            media_paths=[str(p) for p in paths] if paths else None,
            use_uploads=use_up,
            limit=6,
        )
        if not media:
            return None
        analysis = analyze_upload_visibility(
            media,
            aspect=str(parsed.get("aspect") or "9:16"),
        )
        if not analysis.get("needs_ask"):
            parsed.setdefault("fit_mode", "contain")
            parsed["visibility_confirmed"] = True
            return None
        # User already chose fit/aspect in the same message
        if parsed.get("fit_mode") in ("contain", "cover", "letterbox", "pad", "full"):
            parsed["visibility_confirmed"] = True
            return None
        save_pending({**parsed, "pending_kind": "visibility", "visibility": analysis})
        return visibility_ask_message(analysis, topic=str(parsed.get("topic") or ""))
    except Exception:
        parsed.setdefault("fit_mode", "contain")
        return None


def try_mira_command(text: str, *, background: bool = False) -> str | None:
    """If text is a Mira generate/rate/edit command, run it (optionally async)."""
    raw = (text or "").strip()
    if not raw:
        return None

    # Growth schedule (auto-post every N hours)
    try:
        from jarvis.mira.schedule import is_schedule_intent, parse_schedule_command, start_schedule

        if is_schedule_intent(raw):
            parsed = parse_schedule_command(raw)
            if parsed:
                if parsed.get("action") == "schedule_start" and parsed.get("post_now"):
                    start_schedule(
                        list(parsed.get("topics") or []),
                        interval_hours=float(parsed.get("interval_hours") or 3.5),
                        post_now=False,
                    )
                    job = {"action": "schedule_post_now"}
                    if background:
                        from jarvis.tools.mira_jobs import start_job

                        return start_job(job, raw)
                    return run_parsed_action(job)
                return run_parsed_action(parsed)
    except Exception:
        pass

    # Analytics / topic intelligence
    try:
        from jarvis.mira.analytics import parse_analytics_command

        parsed = parse_analytics_command(raw)
        if parsed:
            return run_parsed_action(parsed)
    except Exception:
        pass

    # Multi-platform export
    try:
        from jarvis.mira.export_platforms import is_export_intent, export_platforms

        if is_export_intent(raw):
            if background:
                from jarvis.tools.mira_jobs import start_job

                return start_job({"action": "export_platforms"}, raw)
            return export_platforms().get("message") or "Export done."
    except Exception:
        pass

    # Comment replies
    try:
        from jarvis.mira.comments import is_comment_intent

        if is_comment_intent(raw):
            return run_parsed_action({"action": "reply_comments"})
    except Exception:
        pass

    if re.search(r"\b(clip\s+library|library\s+status)\b", raw, re.I):
        return run_parsed_action({"action": "clip_library_status"})

    # Clip last/long video into vertical Shorts (Vugola clipping play)
    try:
        from jarvis.mira.clipping import (
            extract_clip_topic_hint,
            looks_like_clip_command,
            wants_clip_upload,
        )

        if looks_like_clip_command(raw):
            parsed = {
                "action": "clip_shorts",
                "topic": extract_clip_topic_hint(raw),
                "upload": wants_clip_upload(raw),
                "max_clips": 4,
                "privacy": "public",
            }
            if background:
                from jarvis.tools.mira_jobs import start_job

                return start_job(parsed, raw)
            return run_parsed_action(parsed)
    except Exception:
        pass

    # Growth Shorts factory (Vugola-style: make + hook + public publish)
    try:
        from jarvis.mira.growth import extract_growth_topic, is_growth_post_intent

        if is_growth_post_intent(raw):
            topic = extract_growth_topic(raw)
            parsed = {"action": "growth_post", "topic": topic}
            if background:
                from jarvis.tools.mira_jobs import start_job

                return start_job(parsed, raw)
            return run_parsed_action(parsed)
    except Exception:
        pass

    # Cancel pending format ask
    if re.search(r"\b(cancel|never\s*mind|forget\s+it|stop)\b", raw, re.I):
        try:
            from jarvis.mira.session import clear_pending, load_pending

            if load_pending():
                clear_pending()
                return "Cancelled, sir. Tell me a new video idea whenever you're ready."
        except Exception:
            pass

    # Resume pending brief after visibility / format / mood reply
    try:
        from jarvis.mira.formats import apply_format, format_menu, parse_format_reply
        from jarvis.mira.session import clear_pending, load_pending, save_pending
        from jarvis.mira.visibility import parse_visibility_reply

        pending = load_pending()
        if pending and str(pending.get("pending_kind") or "") == "visibility":
            vis = parse_visibility_reply(raw)
            if vis and vis.get("_cancelled"):
                clear_pending()
                return "Cancelled, sir. Upload again or tell me a new brief."
            if vis and vis.get("confirmed"):
                parsed = {**pending}
                parsed.pop("pending_kind", None)
                parsed.pop("visibility", None)
                parsed["fit_mode"] = vis.get("fit_mode") or "contain"
                parsed["visibility_confirmed"] = True
                if vis.get("aspect"):
                    parsed["aspect"] = vis["aspect"]
                    if vis["aspect"] == "9:16":
                        parsed["format"] = "youtube_shorts"
                    elif vis["aspect"] == "16:9":
                        parsed["format"] = "youtube"
                clear_pending()
                if background:
                    from jarvis.tools.mira_jobs import start_job

                    return start_job(parsed, raw)
                return run_parsed_action(parsed)
            if not is_mira_generate_intent(raw):
                from jarvis.mira.visibility import visibility_ask_message

                return visibility_ask_message(
                    pending.get("visibility") or {},
                    topic=str(pending.get("topic") or ""),
                )
            # New generate intent replaces pending
            clear_pending()

        pending = load_pending()
        if pending and str(pending.get("pending_kind") or "") != "visibility":
            from jarvis.mira.formats import looks_like_new_brief

            # New idea ALWAYS replaces pending — never reuse old topic visuals
            if looks_like_new_brief(raw) or (
                is_mira_generate_intent(raw)
                and len(raw.split()) > 4
                and re.search(r"\b(about|showing|featuring)\b", raw, re.I)
            ):
                clear_pending()
                pending = None
            reply = parse_format_reply(raw) if pending else None
            if not pending:
                pass  # fall through to fresh parse below
            elif not reply and is_mira_generate_intent(raw) and len(raw.split()) > 4:
                clear_pending()
            elif reply:
                fmt = reply.get("format") or pending.get("format")
                mood = reply.get("mood") or pending.get("mood")
                if not fmt:
                    # Mood-only reply — ask format again
                    save_pending({**pending, "mood": mood})
                    return format_menu(str(pending.get("topic") or ""), mood=mood)
                applied = apply_format(fmt)
                parsed = {
                    **pending,
                    "action": "video",
                    "format": fmt,
                    "mood": mood,
                    "aspect": applied["aspect"],
                    "duration_sec": str(applied["duration_sec"]),
                    "format_label": applied.get("format_label"),
                    "needs_format": False,
                }
                clear_pending()
                ask = _visibility_gate(parsed)
                if ask:
                    return ask
                if background:
                    from jarvis.tools.mira_jobs import start_job

                    return start_job(parsed, raw)
                return run_parsed_action(parsed)
            elif not is_mira_generate_intent(raw):
                # Still waiting — remind
                return format_menu(str(pending.get("topic") or ""), mood=pending.get("mood"))
    except Exception:
        pass

    # YouTube connect / upload / caption reply
    try:
        from jarvis.mira.youtube_upload import (
            clear_pending_upload,
            is_youtube_upload_intent,
            parse_caption_reply,
            parse_upload_command,
        )

        yt = parse_upload_command(raw)
        if yt:
            if yt.get("action") in ("youtube_connect", "youtube_status", "youtube_upload_ask"):
                return run_parsed_action(yt)
            if background:
                from jarvis.tools.mira_jobs import start_job

                return start_job(yt, raw)
            return run_parsed_action(yt)

        # Caption / title reply after "upload last video to youtube"
        if not is_youtube_upload_intent(raw):
            caption = parse_caption_reply(raw)
            if caption is not None:
                if caption.get("_cancelled"):
                    return "Cancelled YouTube upload, sir."
                clear_pending_upload()
                yt_job = {
                    "action": "youtube_upload",
                    "privacy": caption.get("privacy") or "public",
                    "title": caption.get("title") or "",
                    "description": caption.get("description") or "",
                    "force_shorts": True,
                }
                if background:
                    from jarvis.tools.mira_jobs import start_job

                    return start_job(yt_job, raw)
                return run_parsed_action(yt_job)
    except Exception:
        pass

    # Edit / crop / reframe last video
    try:
        from jarvis.mira.edit import parse_edit_command

        edit_parsed = parse_edit_command(raw)
        if edit_parsed:
            if background:
                from jarvis.tools.mira_jobs import start_job

                return start_job(edit_parsed, raw)
            return run_parsed_action(edit_parsed)
    except Exception:
        pass

    parsed = parse_mira_command(raw)
    if not parsed:
        return None
    if parsed.get("action") in ("status", "rate"):
        return run_parsed_action(parsed)

    # Inline visibility preference in the same command
    try:
        from jarvis.mira.visibility import parse_visibility_reply

        vis = parse_visibility_reply(raw)
        if vis and not vis.get("_cancelled"):
            if vis.get("fit_mode"):
                parsed["fit_mode"] = vis["fit_mode"]
                parsed["visibility_confirmed"] = True
            if vis.get("aspect"):
                parsed["aspect"] = vis["aspect"]
    except Exception:
        pass

    # Ask format before generating when user didn't specify platform
    if parsed.get("action") == "video" and parsed.get("needs_format"):
        try:
            from jarvis.mira.formats import format_menu
            from jarvis.mira.session import save_pending

            save_pending(parsed)
            return format_menu(str(parsed.get("topic") or ""), mood=parsed.get("mood"))
        except Exception:
            pass

    # Uploads: ask before crop if media won't stay fully visible
    if parsed.get("action") == "video":
        ask = _visibility_gate(parsed)
        if ask:
            return ask

    if background:
        from jarvis.tools.mira_jobs import start_job

        return start_job(parsed, raw)
    return run_parsed_action(parsed)
