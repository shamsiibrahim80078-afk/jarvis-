"""YouTube upload for Mira — OAuth + YouTube Data API v3.

Setup once:
  1. Google Cloud Console → enable YouTube Data API v3
  2. OAuth Desktop client (same JSON as Calendar is fine)
     → data/google_credentials.json OR GOOGLE_CLIENT_ID/SECRET in .env
  3. Say: connect youtube
  4. Say: post this to youtube / upload last video to youtube

Token: data/youtube_token.json
Default privacy: public (everyone can see). Say "unlisted" or "private" to override.
Shorts: vertical 9:16 is forced on upload (auto-crop if needed) so YouTube treats it as a Short.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
CREDENTIALS_PATH = ROOT / "data" / "google_credentials.json"
TOKEN_PATH = ROOT / "data" / "youtube_token.json"
PENDING_PATH = ROOT / "data" / "mira" / "pending_youtube.json"
PENDING_TTL_SEC = 600

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",  # comments / CTA
]


def _reload_env() -> None:
    load_dotenv(ROOT / ".env", override=True)


def _client_config() -> dict | None:
    _reload_env()
    if CREDENTIALS_PATH.exists():
        try:
            data = json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))
            if "installed" in data or "web" in data:
                return data
        except (json.JSONDecodeError, OSError):
            pass
    cid = (os.getenv("GOOGLE_CLIENT_ID") or "").strip()
    csec = (os.getenv("GOOGLE_CLIENT_SECRET") or "").strip()
    if cid and csec:
        return {
            "installed": {
                "client_id": cid,
                "client_secret": csec,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        }
    return None


def config_help() -> str:
    return (
        "YouTube is not connected yet, sir.\n"
        "1) Google Cloud Console → enable YouTube Data API v3\n"
        "2) OAuth Desktop credentials → data/google_credentials.json "
        "(or GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET in .env)\n"
        "3) Say: connect youtube\n"
        "A browser will open once to approve upload access.\n"
        "Then: post last video to youtube"
    )


def credentials_ready() -> bool:
    return _client_config() is not None


def connected() -> bool:
    return TOKEN_PATH.exists() and credentials_ready()


def _build_flow():
    from google_auth_oauthlib.flow import InstalledAppFlow

    cfg = _client_config()
    if not cfg:
        return None
    return InstalledAppFlow.from_client_config(cfg, SCOPES)


def _load_creds():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if not TOKEN_PATH.exists():
        return None
    try:
        # Refresh with scopes already granted — requesting extras (e.g. force-ssl)
        # against an older token causes invalid_scope and blocks all uploads.
        raw = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
        file_scopes = list(raw.get("scopes") or []) or list(SCOPES)
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), file_scopes)
    except Exception:
        return None
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        except Exception:
            return None
    if creds and creds.valid:
        return creds
    return None


def needs_reconnect_for_comments() -> bool:
    """True when comment replies need youtube.force-ssl but token lacks it."""
    if not TOKEN_PATH.exists():
        return True
    try:
        raw = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
        scopes = set(raw.get("scopes") or [])
    except Exception:
        return True
    return "https://www.googleapis.com/auth/youtube.force-ssl" not in scopes


def connect() -> str:
    if not credentials_ready():
        return config_help()
    existing = _load_creds()
    if existing and not needs_reconnect_for_comments():
        return "YouTube already connected, sir. Try: post last video to youtube"
    try:
        flow = _build_flow()
        if not flow:
            return config_help()
        # Always request full SCOPES on connect so comments + upload work
        creds = flow.run_local_server(port=0)
        TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        return (
            "YouTube connected, sir. "
            "Generate a Mira video, then say: post last video to youtube"
        )
    except Exception as exc:
        return f"YouTube connect failed: {exc}"


def status() -> str:
    if not credentials_ready():
        return config_help()
    if connected() and _load_creds():
        extra = ""
        if needs_reconnect_for_comments():
            extra = " (say connect youtube again for comment replies)"
        return f"YouTube connected and ready to upload, sir.{extra}"
    return "YouTube credentials found but not authorized. Say: connect youtube"


def _resolve_video(path: str | None = None) -> Path | None:
    from jarvis.mira.edit import resolve_source

    return resolve_source(path)


def clear_pending_upload() -> None:
    try:
        PENDING_PATH.unlink(missing_ok=True)
    except OSError:
        pass


def load_pending_upload() -> dict[str, Any] | None:
    if not PENDING_PATH.is_file():
        return None
    try:
        data = json.loads(PENDING_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        clear_pending_upload()
        return None
    if not isinstance(data, dict):
        clear_pending_upload()
        return None
    created = float(data.get("created_at") or 0)
    if created and (time.time() - created) > PENDING_TTL_SEC:
        clear_pending_upload()
        return None
    return data


def save_pending_upload(data: dict[str, Any]) -> None:
    PENDING_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(data)
    payload["created_at"] = time.time()
    PENDING_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _open_chrome(url: str) -> None:
    try:
        from jarvis.tools.system import open_in_chrome

        open_in_chrome(url, new_window=False)
    except Exception:
        pass


def begin_upload_flow(*, privacy: str = "public", title: str = "") -> str:
    """Open YouTube Studio and ask for title/captions (optional slow path)."""
    if not credentials_ready():
        return config_help()
    if not connected() or not _load_creds():
        return "YouTube credentials found but not authorized. Say: connect youtube"

    src = _resolve_video(None)
    if not src or not src.is_file():
        return "No video file to upload. Generate one with Mira first."

    from jarvis.mira.last_output import load_last_output

    last = load_last_output() or {}
    default_title = (title or last.get("topic") or src.stem.replace("_", " ") or "Mira Short").strip()[:95]

    _open_chrome("https://studio.youtube.com")
    save_pending_upload(
        {
            "privacy": privacy or "unlisted",
            "default_title": default_title,
            "path": str(src),
        }
    )
    return (
        "Opened YouTube Studio in Chrome, sir. "
        f"Default title: {default_title}. "
        "Reply: `title: My Title | captions: …` — or say `post now`."
    )


def parse_caption_reply(text: str) -> dict[str, str] | None:
    """Parse title/captions reply while a YouTube upload is pending."""
    pending = load_pending_upload()
    if not pending:
        return None
    raw = (text or "").strip()
    if not raw:
        return None
    lower = raw.lower()
    if re.search(r"\b(cancel|never\s*mind|forget\s+it|stop)\b", lower):
        clear_pending_upload()
        return {"_cancelled": "1"}
    if re.search(r"\b(post\s+now|upload\s+now|just\s+post|skip(\s+captions)?|use\s+defaults?)\b", lower):
        return {
            "title": str(pending.get("default_title") or "Mira Short"),
            "description": "",
            "privacy": str(pending.get("privacy") or "public"),
        }

    title = ""
    captions = ""
    tm = re.search(
        r"(?:title|named?)\s*[:=]\s*[\"']?(.+?)[\"']?(?:\s*[|./]\s*|\s+(?:captions?|description|desc)\s*[:=]|$)",
        raw,
        re.I,
    )
    if tm:
        title = tm.group(1).strip().strip("\"'")
    cm = re.search(
        r"(?:captions?|description|desc|details)\s*[:=]\s*[\"']?(.+?)[\"']?\s*$",
        raw,
        re.I | re.S,
    )
    if cm:
        captions = cm.group(1).strip().strip("\"'")
    if not title and not captions:
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        if len(lines) >= 2:
            title, captions = lines[0], "\n".join(lines[1:])
        elif len(raw) > 80:
            title = str(pending.get("default_title") or "Mira Short")
            captions = raw
        else:
            title = raw
            captions = ""
    if not title:
        title = str(pending.get("default_title") or "Mira Short")
    return {
        "title": title[:95],
        "description": captions[:4800],
        "privacy": str(pending.get("privacy") or "public"),
    }


def _probe_is_vertical(path: Path) -> bool:
    try:
        import subprocess

        import imageio_ffmpeg

        ff = imageio_ffmpeg.get_ffmpeg_exe()
        proc = subprocess.run(
            [ff, "-i", str(path)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        m = re.search(r"(\d{3,4})x(\d{3,4})", proc.stderr or "")
        if m:
            return int(m.group(2)) > int(m.group(1))
    except Exception:
        pass
    return False


def _ensure_youtube_channel(youtube) -> dict[str, Any] | None:
    """Return error dict if this Google account has no YouTube channel yet."""
    try:
        resp = youtube.channels().list(part="id,snippet", mine=True).execute()
        items = resp.get("items") or []
        if items:
            return None
    except Exception as exc:
        err = str(exc)
        if "youtubeSignupRequired" not in err and "Unauthorized" not in err:
            return None
    _open_chrome("https://www.youtube.com/create_channel")
    return {
        "ok": False,
        "message": (
            "This Google account has no YouTube channel yet, sir. "
            "I opened Create Channel in Chrome — finish that on "
            "itsjarvisofficial1@gmail.com, then say: upload last video to youtube"
        ),
    }


def _ai_title_description(topic: str, *, is_short: bool) -> tuple[str, str]:
    """Fast title + description for growth uploads (viral Shorts metadata)."""
    if is_short:
        try:
            from jarvis.mira.growth import viral_title_description

            return viral_title_description(topic)
        except Exception:
            pass
    clean = re.sub(r"\s+", " ", (topic or "").strip())
    clean = re.sub(
        r"\b(upload|post|publish|to\s+youtube|youtube\s+shorts?|shorts?|please|for\s+me)\b",
        " ",
        clean,
        flags=re.I,
    )
    clean = re.sub(r"\s+", " ", clean).strip(" .,:;-") or "Mira Short"
    title = clean[:70].rstrip()
    if is_short and "#shorts" not in title.lower():
        title = f"{title} #Shorts"
    title = title[:95]
    desc = (
        f"{clean}\n\nMade with Jarvis Mira.\n#Shorts #YouTubeShorts #AI"
        if is_short
        else f"{clean}\n\nMade with Jarvis Mira."
    )
    return title, desc[:4800]


def _ensure_shorts_file(src: Path, progress_cb=None) -> Path:
    """Guarantee vertical ≤58s Shorts file (YouTube ignores #Shorts on landscape)."""
    def _p(msg: str) -> None:
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    vertical = _probe_is_vertical(src)
    # Probe duration
    dur = 0.0
    try:
        from jarvis.mira.fast_encode import _probe_duration

        dur = float(_probe_duration(src) or 0)
    except Exception:
        dur = 0.0

    need_crop = not vertical
    need_trim = dur > 58.0
    if not need_crop and not need_trim:
        return src

    _p(
        "Converting to YouTube Shorts (9:16 vertical)…"
        if need_crop
        else "Trimming to Shorts length (under 60s)…"
    )
    from jarvis.mira.edit import edit_video

    out = edit_video(
        source=str(src),
        aspect="9:16" if need_crop else None,
        duration_sec=58.0 if (need_trim or need_crop) else None,
        label="shorts",
    )
    if out.get("ok") and out.get("path"):
        p = Path(str(out["path"]))
        if p.is_file():
            try:
                from jarvis.mira.last_output import load_last_output, save_last_output

                last = load_last_output() or {}
                save_last_output({
                    **last,
                    "path": str(p),
                    "video_path": str(p),
                    "aspect": "9:16",
                    "format": "youtube_shorts",
                })
            except Exception:
                pass
            return p
    return src


def upload_video(
    *,
    path: str | None = None,
    title: str = "",
    description: str = "",
    privacy: str = "public",
    tags: list[str] | None = None,
    made_for_kids: bool = False,
    progress_cb=None,
    force_shorts: bool = True,
) -> dict[str, Any]:
    """Upload a local mp4 to YouTube with live Chrome + HUD progress (hunt-style)."""

    def _p(msg: str) -> None:
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    creds = _load_creds()
    if not creds:
        return {"ok": False, "message": config_help() if credentials_ready() else config_help()}

    src = _resolve_video(path)
    if not src or not src.is_file():
        return {"ok": False, "message": "No video file to upload. Generate one with Mira first."}

    priv = (privacy or "public").strip().lower()
    if priv not in ("public", "private", "unlisted"):
        priv = "public"

    from jarvis.mira.last_output import load_last_output

    last = load_last_output() or {}
    fmt = str(last.get("format") or "")
    want_short = bool(force_shorts) or str(last.get("aspect") or "") == "9:16" or fmt in (
        "youtube_shorts",
        "instagram_reels",
        "tiktok",
        "facebook_reels",
        "instagram_stories",
    ) or fmt.endswith("shorts")

    if want_short:
        src = _ensure_shorts_file(src, progress_cb=_p)
    is_short = want_short or _probe_is_vertical(src)

    topic = str(last.get("topic") or src.stem.replace("_", " ") or "Mira Short")
    auto_title, auto_desc = _ai_title_description(topic, is_short=is_short)
    title_f = (title or auto_title).strip()[:95]
    if is_short and "#shorts" not in title_f.lower():
        title_f = f"{title_f[:85].rstrip()} #Shorts"
    base_desc = (description or auto_desc).strip()
    if is_short and "#shorts" not in base_desc.lower():
        base_desc = f"{base_desc}\n\n#Shorts #YouTubeShorts"
    desc_f = base_desc[:4800]
    tag_list = list(tags or ["mira", "jarvis", "ai"])
    if is_short:
        for t in ("shorts", "youtubeshorts", "short"):
            if t not in tag_list:
                tag_list.append(t)
    if last.get("mood"):
        tag_list.append(str(last["mood"]))

    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload

        kind = "Short" if is_short else "video"
        _p(f"Opening YouTube Studio — publishing {kind} as PUBLIC…")
        _open_chrome("https://studio.youtube.com")
        time.sleep(0.35)
        _open_chrome("https://www.youtube.com/upload")
        _p("Watch Chrome: Upload tab open. Checking channel…")

        youtube = build("youtube", "v3", credentials=creds)
        missing = _ensure_youtube_channel(youtube)
        if missing:
            return missing

        _p(f"Preparing {kind}: “{title_f}” (public for everyone)…")
        body = {
            "snippet": {
                "title": title_f,
                "description": desc_f,
                "tags": tag_list[:15],
                "categoryId": "22",
            },
            "status": {
                "privacyStatus": priv,
                "selfDeclaredMadeForKids": bool(made_for_kids),
            },
        }
        media = MediaFileUpload(str(src), mimetype="video/mp4", resumable=True, chunksize=1024 * 1024)
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
        response = None
        last_pct = -1
        _p(f"Uploading {kind}… 0% — live progress in chat")
        while response is None:
            status_prog, response = request.next_chunk()
            if status_prog:
                try:
                    pct = int(status_prog.progress() * 100)
                    if pct >= last_pct + 3 or pct >= 99:
                        last_pct = pct
                        _p(f"Uploading {kind}… {pct}% (Chrome Studio open)")
                except Exception:
                    pass
        vid = response.get("id") if isinstance(response, dict) else None
        url = f"https://youtu.be/{vid}" if vid else ""
        if vid:
            _p("Opening your Short in YouTube Studio…")
            _open_chrome(f"https://studio.youtube.com/video/{vid}/edit")
            time.sleep(0.25)
        if url:
            _p(f"Opening public link… {url}")
            _open_chrome(url)
        clear_pending_upload()
        vis = "PUBLIC — everyone can see" if priv == "public" else priv
        done_msg = (
            f"Done, sir. {kind} published ({vis}): {title_f} — {url}"
            if url
            else f"Done, sir. {kind} published ({vis}): {title_f}"
        )
        _p(done_msg)
        try:
            from jarvis.mira.last_output import load_last_output, save_last_output

            last = load_last_output() or {}
            save_last_output({
                **last,
                "url": url,
                "youtube_url": url,
                "video_id": vid,
                "path": str(src),
                "video_path": str(src),
                "title": title_f,
            })
        except Exception:
            pass
        return {
            "ok": True,
            "video_id": vid,
            "url": url,
            "privacy": priv,
            "title": title_f,
            "path": str(src),
            "is_short": is_short,
            "message": done_msg,
        }
    except Exception as exc:
        err = str(exc)
        if "youtubeSignupRequired" in err or (
            "Unauthorized" in err and "youtube" in err.lower()
        ):
            _open_chrome("https://www.youtube.com/create_channel")
            return {
                "ok": False,
                "message": (
                    "This Google account needs a YouTube channel first, sir. "
                    "I opened Create Channel — finish setup, then retry upload."
                ),
            }
        if "accessNotConfigured" in err or "has not been used" in err:
            return {
                "ok": False,
                "message": (
                    "YouTube Data API is not enabled on this Google Cloud project. "
                    "Enable YouTube Data API v3, then retry."
                ),
            }
        if "invalid_grant" in err or "invalid_rapt" in err:
            try:
                TOKEN_PATH.unlink(missing_ok=True)
            except OSError:
                pass
            return {"ok": False, "message": "YouTube auth expired. Say: connect youtube"}
        return {"ok": False, "message": f"YouTube upload failed: {err}"[:280]}


def is_youtube_connect_intent(text: str) -> bool:
    lower = (text or "").lower()
    return bool(
        re.search(
            r"\b(connect|link|authorize|login|sign\s*in)\b.{0,20}\byoutube\b|"
            r"\byoutube\b.{0,20}\b(connect|auth|login|authorize)\b|"
            r"\byoutube\s+status\b",
            lower,
        )
    )


def is_youtube_upload_intent(text: str) -> bool:
    lower = (text or "").lower()
    # Don't treat "make a youtube shorts about X" as upload
    if re.search(r"\b(make|create|generate|render|produce)\b", lower):
        return False
    return bool(
        re.search(
            r"\b(upload|post|publish|share)\b.{0,40}\byoutube\b|"
            r"\byoutube\b.{0,30}\b(upload|post|publish)\b|"
            r"\b(post|upload)\s+(?:this|it|last|that|the)\s+(?:last\s+)?(?:video|clip|short|reel)\b|"
            r"\b(post|upload)\s+(?:to\s+)?(?:yt|youtube)\b",
            lower,
        )
    )


def parse_upload_command(text: str) -> dict[str, Any] | None:
    if is_youtube_connect_intent(text):
        lower = (text or "").lower()
        if "status" in lower:
            return {"action": "youtube_status"}
        return {"action": "youtube_connect"}
    if not is_youtube_upload_intent(text):
        return None
    lower = (text or "").lower()
    # Default PUBLIC so subscribers / Shorts feed can see it
    privacy = "public"
    if re.search(r"\bunlisted\b", lower):
        privacy = "unlisted"
    elif re.search(r"\bprivate\b", lower):
        privacy = "private"
    # Shorts-first: always vertical Short unless user asks for long video
    force_shorts = True
    if re.search(r"\b(long\s*form|full\s+youtube|youtube\s+video|landscape)\b", lower) and not re.search(
        r"\bshorts?\b", lower
    ):
        force_shorts = False
    if re.search(r"\b(shorts?|reels?|tiktok|vertical)\b", lower):
        force_shorts = True
    title = ""
    tm = re.search(r"(?:title|named?)\s*[:=]?\s*[\"']([^\"']+)[\"']", text or "", re.I)
    if tm:
        title = tm.group(1).strip()
    description = ""
    dm = re.search(
        r"(?:captions?|description|desc)\s*[:=]?\s*[\"']([^\"']+)[\"']",
        text or "",
        re.I,
    )
    if dm:
        description = dm.group(1).strip()
    skip_ask = True
    if re.search(r"\b(with\s+captions?|ask\s+(?:me\s+)?captions?|custom\s+title)\b", lower):
        skip_ask = False
    if title or description:
        skip_ask = True
    return {
        "action": "youtube_upload_ask" if not skip_ask else "youtube_upload",
        "privacy": privacy,
        "title": title,
        "description": description,
        "force_shorts": force_shorts,
    }
