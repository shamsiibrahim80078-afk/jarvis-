"""Read pasted screenshots / chat images — uses GROQ_API_KEY first when present."""

from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

LAST_PATH = ROOT / "data" / "mira" / "last_chat_image.json"
CHAT_IMG_DIR = ROOT / "data" / "mira" / "chat_images"

# Groq vision-capable models (tried in order). Override with GROQ_VISION_MODEL.
_GROQ_VISION_MODELS = (
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
    "llama-3.2-11b-vision-preview",
    "llama-3.2-90b-vision-preview",
)


def _ensure_dirs() -> None:
    CHAT_IMG_DIR.mkdir(parents=True, exist_ok=True)
    (ROOT / "data" / "mira").mkdir(parents=True, exist_ok=True)


def save_chat_image(filename: str, data: bytes, *, also_mira_upload: bool = True) -> Path:
    """Save pasted screenshot for reading + optional Mira upload pack."""
    _ensure_dirs()
    from jarvis.mira.uploads import save_upload

    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in (filename or "paste.png"))[:48]
    if not Path(safe).suffix:
        safe += ".png"
    dest = CHAT_IMG_DIR / f"{int(time.time())}_{safe}"
    dest.write_bytes(data)

    upload_path = None
    if also_mira_upload:
        try:
            upload_path = save_upload(filename or "screenshot.png", data)
        except Exception:
            upload_path = None

    meta = {
        "path": str(dest.resolve()),
        "upload_path": str(upload_path) if upload_path else None,
        "name": dest.name,
        "bytes": len(data),
        "saved_at": time.time(),
    }
    LAST_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return dest.resolve()


def last_chat_image() -> dict[str, Any] | None:
    if not LAST_PATH.is_file():
        return None
    try:
        data = json.loads(LAST_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _mime_for(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
    }.get(ext, "image/png")


def _b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _local_hint(path: Path) -> str:
    try:
        from PIL import Image

        im = Image.open(path)
        w, h = im.size
        return f"Image {w}x{h} ({im.mode}, {path.suffix})."
    except Exception as exc:
        return f"Saved image ({path.name}). Could not inspect locally: {exc}"


def _vision_openai_compat(
    path: Path,
    *,
    prompt: str,
    base_url: str,
    api_key: str,
    model: str,
    extra_headers: dict[str, str] | None = None,
) -> tuple[str | None, str | None]:
    """Returns (text, error)."""
    import httpx

    url = base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        **(extra_headers or {}),
    }
    body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{_mime_for(path)};base64,{_b64(path)}",
                        },
                    },
                ],
            }
        ],
        "max_tokens": 800,
        "temperature": 0.2,
    }
    try:
        timeout = httpx.Timeout(15.0, connect=5.0)
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, headers=headers, json=body)
            if resp.status_code >= 400:
                return None, f"HTTP {resp.status_code}: {(resp.text or '')[:160]}"
            data = resp.json()
            choices = data.get("choices") or []
            if not choices:
                return None, "empty choices"
            msg = (choices[0].get("message") or {}).get("content") or ""
            text = str(msg).strip()
            return (text or None), (None if text else "empty content")
    except Exception as exc:
        return None, str(exc)[:160]


def _vision_gemini(path: Path, prompt: str) -> tuple[str | None, str | None]:
    key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if not key:
        return None, "no_key"
    try:
        import google.generativeai as genai

        genai.configure(api_key=key)
        model_name = (os.getenv("GEMINI_VISION_MODEL") or "gemini-2.0-flash").strip()
        model = genai.GenerativeModel(model_name)
        result = model.generate_content(
            [prompt, {"mime_type": _mime_for(path), "data": path.read_bytes()}]
        )
        text = (getattr(result, "text", None) or "").strip()
        return (text or None), (None if text else "empty")
    except Exception as exc:
        return None, str(exc)[:160]


def read_image(path: str | Path, *, question: str = "") -> dict[str, Any]:
    """Describe / OCR a screenshot. Uses existing GROQ_API_KEY first."""
    p = Path(path).expanduser()
    if not p.is_file():
        return {"ok": False, "message": f"Image not found: {p}"}

    q = (question or "").strip() or (
        "Read this screenshot carefully. Extract all visible text (OCR). "
        "Then briefly describe what is on screen and what the user likely needs. "
        "Be concrete and structured."
    )
    local = _local_hint(p)
    errors: list[str] = []

    groq_key = (os.getenv("GROQ_API_KEY") or "").strip()
    if groq_key:
        models: list[str] = []
        env_m = (os.getenv("GROQ_VISION_MODEL") or "").strip()
        if env_m:
            models.append(env_m)
        # One primary + one fallback — don't chain 4× timeouts
        models.extend(
            [
                "meta-llama/llama-4-scout-17b-16e-instruct",
                "llama-3.2-11b-vision-preview",
            ]
        )
        seen: set[str] = set()
        for model in models:
            if model in seen:
                continue
            seen.add(model)
            text, err = _vision_openai_compat(
                p,
                prompt=q,
                base_url="https://api.groq.com/openai/v1",
                api_key=groq_key,
                model=model,
            )
            if text:
                return {
                    "ok": True,
                    "provider": "groq",
                    "model": model,
                    "text": text,
                    "local": local,
                    "path": str(p),
                }
            if err:
                errors.append(f"groq/{model}: {err}")
                # Network/connect failures: don't burn more models
                if "Connect" in err or "Timeout" in err or "timed out" in err.lower():
                    break

    if (os.getenv("GEMINI_API_KEY") or "").strip():
        text, err = _vision_gemini(p, q)
        if text:
            return {"ok": True, "provider": "gemini", "text": text, "local": local, "path": str(p)}
        if err and err != "no_key":
            errors.append(f"gemini: {err}")

    or_key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
    if or_key:
        model = (os.getenv("OPENROUTER_VISION_MODEL") or "google/gemini-2.0-flash-exp:free").strip()
        text, err = _vision_openai_compat(
            p,
            prompt=q,
            base_url="https://openrouter.ai/api/v1",
            api_key=or_key,
            model=model,
            extra_headers={
                "HTTP-Referer": "https://github.com/jarvis-local",
                "X-Title": "Jarvis Screenshot Reader",
            },
        )
        if text:
            return {"ok": True, "provider": "openrouter", "text": text, "local": local, "path": str(p)}
        if err:
            errors.append(f"openrouter: {err}")

    hint = "; ".join(errors[:2]) if errors else "no vision response"
    return {
        "ok": False,
        "provider": None,
        "text": f"{local} Saved for Mira, but vision read failed ({hint}).",
        "local": local,
        "path": str(p),
        "errors": errors[:4],
        "message": "Image saved; vision read failed.",
    }


def handle_paste(data: bytes, filename: str = "screenshot.png", *, question: str = "") -> dict[str, Any]:
    """Save pasted bytes + read them with Groq (or other vision)."""
    if not data:
        return {"ok": False, "message": "Empty paste."}
    if len(data) > 25 * 1024 * 1024:
        return {"ok": False, "message": "Screenshot too large (max 25MB)."}
    path = save_chat_image(filename, data, also_mira_upload=True)
    read = read_image(path, question=question)
    return {
        "ok": True,
        "saved": True,
        "path": str(path),
        "upload_path": (last_chat_image() or {}).get("upload_path"),
        "read_ok": bool(read.get("ok")),
        "provider": read.get("provider"),
        "model": read.get("model"),
        "text": read.get("text") or read.get("message") or "",
        "errors": read.get("errors") or [],
        "message": (
            "Screenshot pasted — saved for Mira, and I read it with Groq."
            if read.get("ok") and read.get("provider") == "groq"
            else (
                "Screenshot pasted — saved for Mira, and I read it."
                if read.get("ok")
                else "Screenshot pasted and saved for Mira; vision read failed (see text)."
            )
        ),
    }


def is_read_screenshot_intent(text: str) -> bool:
    import re

    t = (text or "").lower()
    return bool(
        re.search(
            r"\b(read|what.?s\s+in|describe|ocr|extract\s+text)\b.{0,30}\b"
            r"(screenshot|screen\s*shot|image|picture|photo|paste|this)\b"
            r"|\b(read|ocr)\s+(the\s+)?(last\s+)?(screenshot|image|paste)\b"
            r"|\bwhat\s+do\s+you\s+see\b",
            t,
        )
    )


def read_last_or_message(text: str = "") -> str:
    meta = last_chat_image()
    if not meta or not meta.get("path"):
        return "No pasted screenshot yet, sir. Ctrl+V an image into the chat box."
    path = Path(str(meta["path"]))
    if not path.is_file():
        return "Last pasted image is missing from disk. Paste again, sir."
    import re

    q2 = re.sub(
        r"\b(read|ocr|describe|what.?s\s+in|extract\s+text)\b.{0,20}\b"
        r"(the\s+)?(last\s+)?(screenshot|image|picture|paste|this)\b",
        " ",
        (text or "").strip(),
        flags=re.I,
    ).strip()
    out = read_image(path, question=q2 or "")
    body = out.get("text") or out.get("message") or "Could not read image."
    return f"{body}\n\n(File: {path.name})"
