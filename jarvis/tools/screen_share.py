"""Dual screen-share: user→Jarvis vision, and Jarvis→HUD live view."""

from __future__ import annotations

import base64
import io
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

logger = logging.getLogger("jarvis.screen_share")

# ── State ────────────────────────────────────────────────

_lock = threading.RLock()

_user_sharing = False
_user_frame_jpeg: bytes | None = None
_user_frame_ts: float = 0.0

_jarvis_sharing = False
_jarvis_frame_jpeg: bytes | None = None
_jarvis_frame_ts: float = 0.0
_jarvis_source = "none"  # playwright | desktop | none
_capture_thread: threading.Thread | None = None
_capture_gen = 0
_stop_capture = threading.Event()

FRAME_MAX_AGE_S = 8.0
# Jarvis→HUD capture target ~6–8 fps (desktop mss); Playwright may be slower.
CAPTURE_INTERVAL_S = 0.12
JPEG_QUALITY = 55
MAX_DIM = 1280
# Vision API payload: smaller = faster upload + inference
VISION_MAX_DIM = 896
VISION_JPEG_QUALITY = 50
RECENT_FRAME_S = 1.0  # use cached frame immediately if fresher than this

_VISION_HINT_RE = re.compile(
    r"\b("
    r"where am i|what am i|what('?s| is) (this|on (my|the) screen)|"
    r"look at|can you see|what do you see|help (me )?with (this|that)|"
    r"read (this|that|the)|describe|what('?s| is) (on|in) (my|the)|"
    r"screen|watching|watching me|see (my|this)|this page|this app|"
    r"what should i|next step|how do i"
    r")\b",
    re.I,
)


# ── User share (HUD → backend) ───────────────────────────

def start_user_share() -> str:
    with _lock:
        global _user_sharing
        _user_sharing = True
    return "Screen share active, sir. Ask me anything about what you see."


def stop_user_share() -> str:
    with _lock:
        global _user_sharing, _user_frame_jpeg, _user_frame_ts
        _user_sharing = False
        _user_frame_jpeg = None
        _user_frame_ts = 0.0
    return "Stopped watching your screen, sir."


def is_user_sharing() -> bool:
    with _lock:
        return _user_sharing


def set_user_frame(jpeg_bytes: bytes) -> None:
    with _lock:
        global _user_frame_jpeg, _user_frame_ts, _user_sharing
        if not jpeg_bytes:
            return
        _user_frame_jpeg = jpeg_bytes
        _user_frame_ts = time.time()
        _user_sharing = True


def get_user_frame() -> tuple[bytes | None, float]:
    with _lock:
        return _user_frame_jpeg, _user_frame_ts


def has_fresh_user_frame() -> bool:
    with _lock:
        if not _user_sharing or not _user_frame_jpeg:
            return False
        return (time.time() - _user_frame_ts) < FRAME_MAX_AGE_S


def should_use_vision(text: str) -> bool:
    """Use vision for any non-trivial question while user is sharing a fresh frame."""
    if not has_fresh_user_frame():
        return False
    lower = text.lower().strip()
    if len(lower) < 2:
        return False
    # Always vision when sharing + asking something that looks like a question/help
    if "?" in text or _VISION_HINT_RE.search(lower):
        return True
    # Short action verbs without screen context → skip vision (open chrome, etc.)
    if re.match(r"^(open|launch|close|search|google|mute|volume|lock)\b", lower):
        return False
    # Default while sharing: use the frame (agent watches them)
    return True


# ── Jarvis share (backend → HUD) ─────────────────────────

def start_jarvis_share() -> str:
    global _jarvis_sharing, _capture_thread, _stop_capture, _capture_gen
    with _lock:
        if _jarvis_sharing and _capture_thread and _capture_thread.is_alive():
            return "Already sharing my screen on the HUD, sir."
        _jarvis_sharing = True
        _capture_gen += 1
        gen = _capture_gen
        _stop_capture.clear()
    _capture_thread = threading.Thread(
        target=_capture_loop, args=(gen,), daemon=True, name="jarvis-screen-share"
    )
    _capture_thread.start()
    return "Sharing my screen on the HUD now, sir. Look at JARVIS SCREEN."


def stop_jarvis_share() -> str:
    global _jarvis_sharing, _jarvis_frame_jpeg, _jarvis_frame_ts, _jarvis_source, _capture_gen
    with _lock:
        _jarvis_sharing = False
        _capture_gen += 1
        _jarvis_frame_jpeg = None
        _jarvis_frame_ts = 0.0
        _jarvis_source = "none"
    _stop_capture.set()
    return "Stopped sharing my screen on the HUD, sir."


def is_jarvis_sharing() -> bool:
    with _lock:
        return _jarvis_sharing


def get_jarvis_frame() -> tuple[bytes | None, float, str]:
    with _lock:
        return _jarvis_frame_jpeg, _jarvis_frame_ts, _jarvis_source


def get_status() -> dict[str, Any]:
    with _lock:
        return {
            "user_sharing": _user_sharing,
            "user_frame_age_s": round(time.time() - _user_frame_ts, 1) if _user_frame_ts else None,
            "user_has_frame": bool(_user_frame_jpeg),
            "jarvis_sharing": _jarvis_sharing,
            "jarvis_frame_age_s": round(time.time() - _jarvis_frame_ts, 1) if _jarvis_frame_ts else None,
            "jarvis_has_frame": bool(_jarvis_frame_jpeg),
            "jarvis_source": _jarvis_source,
        }


# ── Capture helpers ──────────────────────────────────────

def _to_jpeg(img: Any, max_dim: int = MAX_DIM, quality: int = JPEG_QUALITY) -> bytes | None:
    """Convert PIL Image or raw RGB to compressed JPEG bytes."""
    try:
        from PIL import Image
    except ImportError:
        buf = io.BytesIO()
        try:
            img.save(buf, format="JPEG", quality=quality)
            return buf.getvalue()
        except Exception:
            return None

    if not isinstance(img, Image.Image):
        try:
            img = Image.fromarray(img)
        except Exception:
            return None

    w, h = img.size
    scale = min(1.0, max_dim / max(w, h))
    if scale < 1.0:
        # BILINEAR is fast enough; avoid LANCZOS (slower)
        img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.BILINEAR)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    # optimize=True is CPU-heavy — skip for stream fps
    img.save(buf, format="JPEG", quality=quality, optimize=False)
    return buf.getvalue()


def _shrink_jpeg(jpeg: bytes, max_dim: int = VISION_MAX_DIM, quality: int = VISION_JPEG_QUALITY) -> bytes:
    """Downscale an existing JPEG for faster vision API calls."""
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(jpeg))
        out = _to_jpeg(img, max_dim=max_dim, quality=quality)
        return out or jpeg
    except Exception:
        return jpeg


def _capture_playwright() -> bytes | None:
    """Screenshot from held Playwright context if present in this process."""
    try:
        from jarvis.tools import api_hunter
        hold = getattr(api_hunter, "_BROWSER_HOLD", None) or []
        if not hold:
            return None
        for obj in hold:
            pages = getattr(obj, "pages", None)
            if pages is None:
                continue
            page_list = list(pages)
            if not page_list:
                continue
            for page in page_list:
                try:
                    png = page.screenshot(type="jpeg", quality=JPEG_QUALITY, timeout=1200)
                    if png:
                        return _shrink_jpeg(png, max_dim=MAX_DIM, quality=JPEG_QUALITY)
                except Exception:
                    continue
    except Exception as exc:
        logger.debug("playwright capture skip: %s", exc)
    return None


def _capture_desktop_mss(sct: Any) -> bytes | None:
    """Grab primary monitor using an existing mss instance."""
    try:
        from PIL import Image

        mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
        shot = sct.grab(mon)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        return _to_jpeg(img)
    except Exception:
        return None


def _capture_desktop() -> bytes | None:
    """Primary-monitor screenshot via mss (preferred) or pyautogui."""
    try:
        import mss

        with mss.mss() as sct:
            return _capture_desktop_mss(sct)
    except Exception:
        pass

    try:
        import pyautogui

        img = pyautogui.screenshot()
        return _to_jpeg(img)
    except Exception as exc:
        logger.warning("desktop capture failed: %s", exc)
        return None


def _capture_once(sct: Any | None = None) -> tuple[bytes | None, str]:
    # Desktop mss first for 5–10 fps; Playwright only when pages exist (slower)
    if sct is not None:
        jpeg = _capture_desktop_mss(sct)
        if jpeg:
            return jpeg, "desktop"
    jpeg = _capture_playwright()
    if jpeg:
        return jpeg, "playwright"
    jpeg = _capture_desktop()
    if jpeg:
        return jpeg, "desktop"
    return None, "none"


def _capture_loop(gen: int) -> None:
    """Background thread — never touches the FastAPI event loop."""
    global _jarvis_frame_jpeg, _jarvis_frame_ts, _jarvis_source
    sct = None
    try:
        import mss

        sct = mss.mss()
    except Exception:
        sct = None

    try:
        while True:
            with _lock:
                if not _jarvis_sharing or gen != _capture_gen:
                    break
            t0 = time.perf_counter()
            try:
                jpeg, source = _capture_once(sct)
                if jpeg:
                    with _lock:
                        if _jarvis_sharing and gen == _capture_gen:
                            _jarvis_frame_jpeg = jpeg
                            _jarvis_frame_ts = time.time()
                            _jarvis_source = source
            except Exception as exc:
                logger.debug("capture loop: %s", exc)
            elapsed = time.perf_counter() - t0
            wait = max(0.0, CAPTURE_INTERVAL_S - elapsed)
            if _stop_capture.wait(wait):
                with _lock:
                    if not _jarvis_sharing or gen != _capture_gen:
                        break
    finally:
        if sct is not None:
            try:
                sct.close()
            except Exception:
                pass


# ── Vision ───────────────────────────────────────────────

def _load_keys() -> dict[str, str]:
    keys = {
        "gemini": os.getenv("GEMINI_API_KEY", ""),
        "groq": os.getenv("GROQ_API_KEY", ""),
        "openrouter": os.getenv("OPENROUTER_API_KEY", ""),
    }
    keys_path = ROOT / "config" / "api_keys.json"
    if keys_path.exists():
        try:
            import json
            data = json.loads(keys_path.read_text(encoding="utf-8"))
            for k, v in data.items():
                if v and not keys.get(k):
                    keys[k] = v
        except Exception:
            pass
    return keys


def _ask_gemini_vision(jpeg: bytes, question: str) -> str | None:
    keys = _load_keys()
    if not keys.get("gemini"):
        return None
    try:
        import google.generativeai as genai
        from PIL import Image
    except ImportError:
        return None

    try:
        genai.configure(api_key=keys["gemini"])
        # Flash is the fastest generally-available Gemini vision path
        model_name = os.getenv("GEMINI_VISION_MODEL", "gemini-2.0-flash")
        model = genai.GenerativeModel(
            model_name,
            system_instruction=(
                "Jarvis desktop agent. Reply in 1-2 short sentences. "
                "Name the app/page and the next step. Call user sir."
            ),
        )
        img = Image.open(io.BytesIO(jpeg))
        result = model.generate_content(
            [question, img],
            generation_config={"max_output_tokens": 80, "temperature": 0.2},
        )
        text = (result.text or "").strip()
        return text or None
    except Exception as exc:
        logger.warning("gemini vision failed: %s", exc)
        return None


def _ask_groq_vision(jpeg: bytes, question: str) -> str | None:
    keys = _load_keys()
    if not keys.get("groq"):
        return None
    try:
        from openai import OpenAI
    except ImportError:
        return None

    b64 = base64.b64encode(jpeg).decode("ascii")
    data_url = f"data:image/jpeg;base64,{b64}"
    model = os.getenv("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
    client = OpenAI(api_key=keys["groq"], base_url="https://api.groq.com/openai/v1")
    try:
        resp = client.chat.completions.create(
            model=model,
            max_tokens=80,
            temperature=0.2,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Jarvis desktop agent. Reply in 1-2 short sentences. "
                        "Name the app/page and the next step. Call user sir."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": question},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
        )
        return (resp.choices[0].message.content or "").strip() or None
    except Exception as exc:
        logger.warning("groq vision failed: %s", exc)
        return None


def _simple_ocr_hint(jpeg: bytes) -> str | None:
    """Best-effort local hint if no vision API — image size / age only."""
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(jpeg))
        w, h = img.size
        return (
            f"I can see your shared screen ({w}x{h}), sir, but no vision model is configured. "
            "Add GEMINI_API_KEY (or Groq vision) to .env so I can describe what you are doing."
        )
    except Exception:
        return (
            "I have your screen frame, sir, but no vision model is available. "
            "Add GEMINI_API_KEY to .env."
        )


def answer_with_vision(question: str) -> str:
    """Answer using the latest user screen frame — never wait for a new capture."""
    jpeg, ts = get_user_frame()
    if not jpeg:
        return "I am not receiving your screen yet, sir. Click Share my screen on the HUD."
    age = time.time() - ts
    if age > FRAME_MAX_AGE_S:
        return "Your screen share frame is stale, sir. Keep sharing and ask again."

    # Use cached frame immediately — never wait for a fresher capture.
    # Frames younger than RECENT_FRAME_S are ideal; older still ok until FRAME_MAX_AGE_S.

    # Downscale before vision API for lower latency
    jpeg = _shrink_jpeg(jpeg)

    prompt = f"Screen Q: {question}"

    # Prefer Gemini flash, then Groq
    for fn in (_ask_gemini_vision, _ask_groq_vision):
        try:
            ans = fn(jpeg, prompt)
            if ans:
                return ans
        except Exception:
            continue

    hint = _simple_ocr_hint(jpeg)
    return hint or "Vision is unavailable, sir. Configure GEMINI_API_KEY."


# ── Fast-router helpers ──────────────────────────────────

_USER_START = (
    "share my screen",
    "start sharing my screen",
    "watch my screen",
    "watch me",
    "start watching me",
)
_USER_STOP = (
    "stop sharing my screen",
    "stop watching my screen",
    "stop watching me",
    "don't watch my screen",
    "do not watch my screen",
)
_JARVIS_START = (
    "share your screen",
    "show me what you're doing",
    "show me what you are doing",
    "show your screen",
    "start sharing your screen",
    "share jarvis screen",
)
_JARVIS_STOP = (
    "stop sharing your screen",
    "stop showing your screen",
    "hide your screen",
    "stop jarvis screen",
)


def is_screen_share_command(text: str) -> bool:
    lower = re.sub(r"\s+", " ", text.lower().strip())
    phrases = _USER_START + _USER_STOP + _JARVIS_START + _JARVIS_STOP
    return any(p in lower for p in phrases)


def handle_screen_share_command(text: str) -> str | None:
    """Handle share phrases without LLM. Returns response or None."""
    if not is_screen_share_command(text):
        return None
    lower = re.sub(r"\s+", " ", text.lower().strip())

    if any(p in lower for p in _USER_STOP):
        return stop_user_share()
    if any(p in lower for p in _JARVIS_STOP):
        return stop_jarvis_share()
    if any(p in lower for p in _JARVIS_START):
        return start_jarvis_share()
    if any(p in lower for p in _USER_START):
        # Browser permission must come from HUD click / auto-prompt
        return (
            "Ready to watch, sir. Click Share my screen on the HUD "
            "(or allow the browser picker when it appears)."
        )
    return None
