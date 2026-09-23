"""Mira free media pipeline for Jarvis — Pollinations stills + Ken Burns + edge-tts."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Optional, Sequence
from urllib.parse import quote

from jarvis.mira.quality import (
    audience_script,
    enhance_still_prompt,
    load_engine_config,
    shot_angles,
)

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = _ROOT / "data" / "mira"

_POLL_BASES = (
    "https://image.pollinations.ai/prompt",
    "https://gen.pollinations.ai/image",
)
_RETRY_BACKOFF_SEC = (2.0, 5.0, 10.0, 18.0)
_DEFAULT_VOICE = "en-US-AndrewNeural"


try:
    from PIL import Image as _PILImage

    if not hasattr(_PILImage, "ANTIALIAS"):
        _PILImage.ANTIALIAS = _PILImage.Resampling.LANCZOS  # type: ignore[attr-defined]
    if not hasattr(_PILImage, "BICUBIC"):
        _PILImage.BICUBIC = _PILImage.Resampling.BICUBIC  # type: ignore[attr-defined]
    if not hasattr(_PILImage, "BILINEAR"):
        _PILImage.BILINEAR = _PILImage.Resampling.BILINEAR  # type: ignore[attr-defined]
except Exception:
    pass


def out_root() -> Path:
    root = DEFAULT_OUT
    for sub in ("images", "audio", "videos"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def _stem(topic: str, prefix: str = "mira") -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", (topic or "topic").strip())[:40].strip("_").lower()
    return f"{prefix}_{slug or 'topic'}_{uuid.uuid4().hex[:8]}"


def _prefer_flux() -> bool:
    raw = (os.getenv("JARVIS_MIRA_QUALITY") or os.getenv("MIRA_QUALITY") or "high").strip().lower()
    if raw in ("fast", "turbo", "low"):
        return False
    if raw in ("0", "false", "no", "off"):
        return False
    return True  # high / flux / default


def _http_get_bytes(url: str, params: dict[str, Any], timeout: float) -> tuple[int, bytes, str]:
    try:
        import httpx

        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(url, params=params)
            ctype = (resp.headers.get("content-type") or "").lower()
            return resp.status_code, resp.content, ctype
    except ImportError:
        from urllib.parse import urlencode
        from urllib.request import Request, urlopen

        qs = urlencode({k: str(v) for k, v in params.items()})
        full = f"{url}?{qs}" if qs else url
        req = Request(full, headers={"User-Agent": "Jarvis-Mira/1.0"})
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310
            ctype = (resp.headers.get("Content-Type") or "").lower()
            return int(getattr(resp, "status", 200) or 200), resp.read(), ctype


def generate_still(
    prompt: str,
    out_path: str | Path,
    width: int = 1280,
    height: int = 720,
    *,
    model: str | None = None,
    timeout: float = 75.0,
    max_attempts: int = 5,
    seed: int | None = None,
    enhance: bool = True,
    raw: bool = False,
) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Locked character/office prompts must stay exact — do not rewrite
    if raw:
        enhanced = re.sub(r"\s+", " ", (prompt or "").strip())
    else:
        enhanced = prompt if len(prompt) > 40 else enhance_still_prompt(prompt)
    # Pollinations URL length blows up → HTTP 400 / ignored scene
    enhanced = enhanced[:520]
    w = max(768, min(1280, int(width or 1280)))
    h = max(768, min(1280, int(height or 720)))
    preferred = model or ("flux" if _prefer_flux() else "turbo")
    models: list[str] = []
    for m in (preferred, "flux", "turbo"):
        if m and m not in models:
            models.append(m)
    if seed is None:
        seed = int(hashlib.md5(enhanced.encode("utf-8", errors="ignore")).hexdigest()[:8], 16) % 2_147_483_647
        seed = (seed + int(time.time()) % 10_000) % 2_147_483_647

    last_err = "unknown"
    for attempt in range(max(1, int(max_attempts))):
        if attempt > 0:
            time.sleep(_RETRY_BACKOFF_SEC[min(attempt - 1, len(_RETRY_BACKOFF_SEC) - 1)])
        use_model = models[min(attempt, len(models) - 1)]
        use_base = _POLL_BASES[attempt % len(_POLL_BASES)]
        params = {
            "width": w,
            "height": h,
            "nologo": "true",
            "enhance": "true" if enhance else "false",
            "model": use_model,
            "seed": int(seed) + attempt,
        }
        url = f"{use_base}/{quote(enhanced)}"
        try:
            status, body, ctype = _http_get_bytes(url, params, timeout=float(timeout))
        except Exception as exc:
            last_err = f"network: {exc}"
            continue
        if status == 429:
            last_err = "HTTP 429 — Pollinations free queue busy"
            continue
        if status == 400:
            last_err = "HTTP 400 — prompt too long or rejected"
            # Retry with a shorter clip of the prompt
            enhanced = enhanced[:360]
            continue
        if status == 200 and (
            "image" in ctype or body[:3] == b"\xff\xd8\xff" or body[:8] == b"\x89PNG\r\n\x1a\n"
        ):
            if len(body) < 4000:
                last_err = "downloaded image too small"
                continue
            out.write_bytes(body)
            return out.resolve()
        last_err = f"HTTP {status} ctype={ctype[:40]!r}"

    raise RuntimeError(
        f"Image generation failed after {max_attempts} attempts ({last_err}). Retry in a minute."
    )


def _upscale_sharpen(path: Path, target_w: int = 1920, target_h: int = 1080) -> Path:
    """Upscale still to 1080p + mild unsharp — big visual upgrade over raw 720p."""
    try:
        from PIL import Image, ImageEnhance, ImageFilter
    except Exception:
        return path
    try:
        # libx264 requires even dimensions
        target_w = max(640, int(target_w) // 2 * 2)
        target_h = max(360, int(target_h) // 2 * 2)
        img = Image.open(path).convert("RGB")
        # Cover-fit then center-crop to exact size
        src_w, src_h = img.size
        scale = max(target_w / max(1, src_w), target_h / max(1, src_h))
        new_w = max(target_w, int(src_w * scale + 0.5))
        new_h = max(target_h, int(src_h * scale + 0.5))
        # Keep even while resizing
        new_w = new_w // 2 * 2
        new_h = new_h // 2 * 2
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        left = max(0, (new_w - target_w) // 2)
        top = max(0, (new_h - target_h) // 2)
        img = img.crop((left, top, left + target_w, top + target_h))
        img = img.filter(ImageFilter.UnsharpMask(radius=1.4, percent=140, threshold=2))
        img = ImageEnhance.Contrast(img).enhance(1.08)
        img = ImageEnhance.Color(img).enhance(1.06)
        out = path.with_name(path.stem + "_hq.jpg")
        img.save(out, "JPEG", quality=94, optimize=True)
        return out.resolve()
    except Exception as exc:
        logger.warning("upscale failed: %s", exc)
        return path


def _force_even_size(clip, major: int, size=(1920, 1080)):
    """Ensure clip is even WxH so libx264 never fails."""
    w, h = int(size[0]) // 2 * 2, int(size[1]) // 2 * 2
    try:
        if major >= 2:
            return clip.resized(new_size=(w, h))
        return clip.resize(newsize=(w, h))
    except Exception:
        try:
            if major >= 2:
                return clip.resized((w, h))
            return clip.resize((w, h))
        except Exception:
            return clip

def generate_images(
    topic: str,
    count: int = 5,
    *,
    width: int = 1280,
    height: int = 720,
    style: str = "cinematic",
    upscale: bool = True,
    prefer_pexels: bool = True,
) -> tuple[list[Path], list[dict[str, Any]], str]:
    """Return (paths, credits, source).

    Expands thin brands (google→laptop/search scenes). Uses filtered Pexels first,
    then Pollinations if needed. Never returns letter-stamp junk as the video.
    """
    root = out_root()
    n = max(3, min(6, int(count or 5)))
    credits: list[dict[str, Any]] = []
    source = "pollinations"

    # Expand thin brands into a real visual prompt (google ≠ wooden letter stamps)
    visual_topic = topic
    prefer_ai = False
    search_topic = topic
    brief_for_pexels = topic
    try:
        from jarvis.mira.intent import expand_ask

        ex = expand_ask(topic)
        visual_topic = str(ex.get("brief") or topic)
        prefer_ai = bool(ex.get("prefer_ai_stills"))
        qs = list(ex.get("search_queries") or [])
        if qs:
            search_topic = str(qs[0])
        brief_for_pexels = str(ex.get("original") or topic)
    except Exception:
        pass

    def _pexels_fill(need: int) -> tuple[list[Path], list[dict[str, Any]]]:
        try:
            from jarvis.mira import pexels as pexels_mod

            if not pexels_mod.configured() or need <= 0:
                return [], []
            orient = "portrait" if height > width else "landscape"
            # Always search expanded scene queries — never raw "google" alone
            return pexels_mod.fetch_stills(
                search_topic,
                root / "images",
                count=need,
                orientation=orient,
                brief=brief_for_pexels,
            )
        except Exception as exc:
            logger.warning("Pexels stills failed: %s", exc)
            return [], []

    # Brands + real-world: filtered Pexels scene stock first (fast, on-brief).
    # prefer_ai used to skip Pexels → hung on dead Pollinations + letter stamps when
    # searching the raw brand word. Expanded queries + junk reject fix that.
    paths: list[Path] = []
    if prefer_pexels or prefer_ai:
        paths, credits = _pexels_fill(n)
        if len(paths) >= max(3, n - 1):
            source = "pexels"
            if upscale:
                tw, th = (1080, 1920) if height > width else (1920, 1080)
                paths = [_upscale_sharpen(p, tw, th) for p in paths]
            return paths, credits, source
        # keep partial; AI may fill below
        if paths:
            source = "pexels"

    ai_paths: list[Path] = []
    angles = shot_angles(n)
    base_seed = int(hashlib.md5(visual_topic.encode("utf-8", errors="ignore")).hexdigest()[:8], 16) % 2_000_000_000
    cfg = load_engine_config()
    timeout = float((cfg.get("still_gen") or {}).get("timeout_sec") or 75)
    ai_timeout = min(timeout, 35.0) if prefer_ai else timeout
    ai_attempts = 2 if prefer_ai else 5
    need_ai = max(0, n - len(paths))
    for i in range(need_ai):
        if prefer_ai:
            short = visual_topic[:180]
            prompt = (
                f"{short}, {angles[i]}, photoreal cinematic, "
                f"real laptop or phone UI scene, no letter toys, no watermark"
            )[:360]
        else:
            prompt = enhance_still_prompt(visual_topic, style=style, shot=angles[i])
        dest = root / "images" / f"{_stem(topic, f'img{i + 1}')}.jpg"
        try:
            p = generate_still(
                prompt,
                dest,
                width=width,
                height=height,
                timeout=ai_timeout,
                max_attempts=ai_attempts,
                seed=base_seed + i * 17,
            )
            if upscale:
                p = _upscale_sharpen(p, 1920 if width >= height else 1080, 1080 if width >= height else 1920)
            ai_paths.append(p)
        except RuntimeError as exc:
            logger.error("Still %s/%s failed: %s", i + 1, need_ai, exc)
            if prefer_ai:
                break
            continue
        if i + 1 < need_ai:
            time.sleep(0.8 if prefer_ai else 1.6)

    if ai_paths:
        if paths:
            source = "pexels+pollinations"
            paths = (paths + ai_paths)[:n]
        else:
            source = "pollinations"
            paths = ai_paths[:n]
        return paths, credits, source

    if paths:
        source = "pexels"
        if upscale:
            tw, th = (1080, 1920) if height > width else (1920, 1080)
            paths = [_upscale_sharpen(p, tw, th) for p in paths]
        return paths, credits, source

    return [], credits, source


def generate_voiceover(
    script: str,
    out_mp3: str | Path,
    voice: str | None = None,
) -> Path:
    text = re.sub(r"\s+", " ", (script or "").strip())
    if not text:
        raise ValueError("script is required")
    out = Path(out_mp3)
    out.parent.mkdir(parents=True, exist_ok=True)
    cfg = load_engine_config()
    audio_cfg = cfg.get("audio") if isinstance(cfg.get("audio"), dict) else {}
    voice_id = (voice or audio_cfg.get("voice") or _DEFAULT_VOICE).strip() or _DEFAULT_VOICE
    rate = str(audio_cfg.get("rate") or "-4%")
    pitch = str(audio_cfg.get("pitch") or "+0Hz")

    try:
        import edge_tts
    except ImportError as exc:
        raise RuntimeError("edge-tts is not installed. Run: pip install edge-tts") from exc

    async def _run() -> None:
        communicate = edge_tts.Communicate(text, voice_id, rate=rate, pitch=pitch)
        await communicate.save(str(out))

    try:
        asyncio.run(_run())
    except RuntimeError as exc:
        if "running event loop" in str(exc).lower() or "asyncio" in str(exc).lower():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(lambda: asyncio.run(_run())).result(timeout=180)
        else:
            raise

    if not out.is_file() or out.stat().st_size < 400:
        raise RuntimeError(f"edge-tts produced empty audio at {out}")
    return out.resolve()


def _patch_pillow_for_moviepy() -> None:
    try:
        from PIL import Image

        _lanczos = getattr(getattr(Image, "Resampling", Image), "LANCZOS", None)
        if not hasattr(Image, "ANTIALIAS") and _lanczos is not None:
            Image.ANTIALIAS = _lanczos  # type: ignore[attr-defined]
    except Exception:
        pass


def _moviepy_api():
    _patch_pillow_for_moviepy()
    try:
        from moviepy import AudioFileClip, CompositeVideoClip, ImageClip, VideoFileClip, concatenate_videoclips

        return {
            "ImageClip": ImageClip,
            "AudioFileClip": AudioFileClip,
            "VideoFileClip": VideoFileClip,
            "CompositeVideoClip": CompositeVideoClip,
            "concatenate_videoclips": concatenate_videoclips,
        }, 2
    except Exception:
        pass
    try:
        from moviepy.editor import (
            AudioFileClip,
            CompositeVideoClip,
            ImageClip,
            VideoFileClip,
            concatenate_videoclips,
        )

        return {
            "ImageClip": ImageClip,
            "AudioFileClip": AudioFileClip,
            "VideoFileClip": VideoFileClip,
            "CompositeVideoClip": CompositeVideoClip,
            "concatenate_videoclips": concatenate_videoclips,
        }, 1
    except Exception:
        return None


def _render_heading_png(text: str, out_path: Path, *, width: int = 1080, height: int = 220) -> Path | None:
    """Instagram-reel style heading bar (Pillow — no ImageMagick)."""
    label = re.sub(r"\s+", " ", (text or "").strip())
    if not label:
        return None
    # RTL reshape for Urdu/Arabic/Pashto/Farsi when libs available
    try:
        if re.search(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]", label):
            import arabic_reshaper
            from bidi.algorithm import get_display

            label = get_display(arabic_reshaper.reshape(label))
    except Exception:
        pass
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    w = max(640, int(width) // 2 * 2)
    h = max(120, int(height) // 2 * 2)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Prefer fonts that support Urdu/Arabic if present on Windows
    font = None
    for name in (
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\tahoma.ttf",
        r"C:\Windows\Fonts\tradbdo.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\seguisb.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
    ):
        try:
            font = ImageFont.truetype(name, 64)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()

    font_path = r"C:\Windows\Fonts\arial.ttf"
    for cand in (
        r"C:\Windows\Fonts\tahoma.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\seguisb.ttf",
    ):
        if Path(cand).is_file():
            font_path = cand
            break

    # Shrink font until text fits
    for size in (64, 54, 46, 38, 32, 26):
        try:
            font = ImageFont.truetype(font_path, size)
        except Exception:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), label, font=font)
        tw = bbox[2] - bbox[0]
        if tw <= w - 80:
            break

    bbox = draw.textbbox((0, 0), label, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = max(20, (w - tw) // 2)
    y = max(10, (h - th) // 2 - 4)
    # Soft dark pill behind text
    pad_x, pad_y = 28, 16
    pill = [x - pad_x, y - pad_y, x + tw + pad_x, y + th + pad_y]
    try:
        draw.rounded_rectangle(pill, radius=18, fill=(0, 0, 0, 150))
    except Exception:
        draw.rectangle(pill, fill=(0, 0, 0, 150))
    # White heading + subtle shadow
    draw.text((x + 2, y + 2), label, font=font, fill=(0, 0, 0, 180))
    draw.text((x, y), label, font=font, fill=(255, 255, 255, 255))
    img.save(out_path, "PNG")
    return out_path.resolve()


def _overlay_heading(clip, heading: str, mods: dict, major: int, ow: int, oh: int, hold: list):
    """Composite reel heading onto lower-third of clip."""
    if not heading:
        return clip
    CompositeVideoClip = mods.get("CompositeVideoClip")
    ImageClip = mods.get("ImageClip")
    if CompositeVideoClip is None or ImageClip is None:
        return clip
    try:
        dur = float(clip.duration or 3.0)
    except Exception:
        dur = 3.0
    tmp = out_root() / "overlays" / f"heading_{uuid.uuid4().hex[:10]}.png"
    png = _render_heading_png(heading, tmp, width=ow, height=max(160, oh // 9))
    if png is None or not png.is_file():
        return clip
    try:
        if major >= 2:
            overlay = ImageClip(str(png)).with_duration(dur)
        else:
            overlay = ImageClip(str(png)).set_duration(dur)
        # Lower third
        y = int(oh * 0.72)
        try:
            if major >= 2 and hasattr(overlay, "with_position"):
                overlay = overlay.with_position(("center", y))
            else:
                overlay = overlay.set_position(("center", y))
        except Exception:
            pass
        hold.append(overlay)
        composed = CompositeVideoClip([clip, overlay], size=(ow, oh))
        if major >= 2:
            composed = composed.with_duration(dur)
        else:
            composed = composed.set_duration(dur)
        # Keep audio from base clip
        try:
            if getattr(clip, "audio", None) is not None:
                if major >= 2:
                    composed = composed.with_audio(clip.audio)
                else:
                    composed = composed.set_audio(clip.audio)
        except Exception:
            pass
        return composed
    except Exception:
        return clip


def _safe_close_many(*objs: Any) -> None:
    import threading

    def _close(obj: Any) -> None:
        try:
            obj.close()
        except Exception:
            pass

    for obj in objs:
        if obj is None:
            continue
        t = threading.Thread(target=_close, args=(obj,), daemon=True)
        t.start()
        t.join(timeout=2.0)


def _write_mp4(video, out: Path, *, fps: int, bitrate: str = "12000k", fast: bool = False) -> None:
    """Stable libx264 write. Default quality path (medium) — matches gold office encodes."""
    preset = "veryfast" if fast else "medium"
    crf = "23" if fast else "17"
    write_kwargs: dict[str, Any] = {
        "fps": int(fps or 30),
        "codec": "libx264",
        "audio_codec": "aac",
        "threads": 4,
        "logger": None,
        "bitrate": bitrate or "12000k",
        "ffmpeg_params": [
            "-crf",
            crf,
            "-preset",
            preset,
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-avoid_negative_ts",
            "make_zero",
        ],
    }
    try:
        video.write_videofile(str(out), **write_kwargs)
        return
    except TypeError:
        write_kwargs.pop("logger", None)
    try:
        video.write_videofile(str(out), **write_kwargs)
        return
    except TypeError:
        write_kwargs.pop("ffmpeg_params", None)
        write_kwargs["bitrate"] = bitrate or "8000k"
        try:
            video.write_videofile(str(out), **write_kwargs)
        except TypeError:
            write_kwargs.pop("bitrate", None)
            video.write_videofile(str(out), **write_kwargs)


def _fit_clip(clip, major: int, ow: int, oh: int):
    """Cover-fit clip into even WxH (center crop feel via resize to fill)."""
    try:
        w, h = float(clip.w), float(clip.h)
    except Exception:
        return _force_even_size(clip, major, (ow, oh))
    if w <= 1 or h <= 1:
        return _force_even_size(clip, major, (ow, oh))
    scale = max(ow / w, oh / h)
    nw = int(w * scale) // 2 * 2
    nh = int(h * scale) // 2 * 2
    try:
        if major >= 2:
            clip = clip.resized(new_size=(nw, nh))
        else:
            clip = clip.resize(newsize=(nw, nh))
    except Exception:
        return _force_even_size(clip, major, (ow, oh))
    # Center crop via crop if available
    try:
        x1 = max(0, (nw - ow) // 2)
        y1 = max(0, (nh - oh) // 2)
        if major >= 2 and hasattr(clip, "cropped"):
            clip = clip.cropped(x1=x1, y1=y1, width=ow, height=oh)
        elif hasattr(clip, "crop"):
            clip = clip.crop(x1=x1, y1=y1, width=ow, height=oh)
        else:
            clip = _force_even_size(clip, major, (ow, oh))
    except Exception:
        clip = _force_even_size(clip, major, (ow, oh))
    return _force_even_size(clip, major, (ow, oh))


def _soft_fade(clip, major: int, fade: float = 0.25):
    fade = max(0.0, min(0.45, float(fade or 0)))
    if fade <= 0.02:
        return clip
    try:
        return clip.fadein(fade).fadeout(fade)
    except Exception:
        return clip


def _sync_audio(video, audio_clip, major: int):
    """Attach audio and hard-trim so A/V lengths never diverge (stops end glitch)."""
    if audio_clip is None:
        return video, None
    try:
        vdur = float(video.duration or 0)
        adur = float(audio_clip.duration or 0)
    except Exception:
        vdur, adur = 0.0, 0.0
    if vdur <= 0:
        return video, audio_clip
    target = vdur
    if adur > 0:
        target = min(vdur, adur)
    # Leave a tiny margin so last encoded frame isn't a torn compose leftover
    target = max(1.0, target - 0.05)
    try:
        if major >= 2:
            if hasattr(video, "subclipped"):
                video = video.subclipped(0, target)
            elif hasattr(video, "subclip"):
                video = video.subclip(0, target)
            if adur > target + 0.01:
                if hasattr(audio_clip, "subclipped"):
                    audio_clip = audio_clip.subclipped(0, target)
                elif hasattr(audio_clip, "subclip"):
                    audio_clip = audio_clip.subclip(0, target)
            video = video.with_audio(audio_clip)
        else:
            video = video.subclip(0, target)
            if adur > target + 0.01:
                audio_clip = audio_clip.subclip(0, target)
            video = video.set_audio(audio_clip)
    except Exception:
        try:
            if major >= 2:
                video = video.with_audio(audio_clip)
            else:
                video = video.set_audio(audio_clip)
        except Exception:
            pass
    return video, audio_clip


def _hold_still_clip(
    mods: dict,
    path: Path,
    duration: float,
    major: int,
    out_size=(1080, 1920),
):
    """Sharp still hold — no Ken Burns zoom (zoom makes AI faces look trashy)."""
    ImageClip = mods["ImageClip"]
    ow, oh = int(out_size[0]) // 2 * 2, int(out_size[1]) // 2 * 2
    if major >= 2:
        clip = ImageClip(str(path)).with_duration(duration)
        try:
            clip = clip.resized(new_size=(ow, oh))
        except Exception:
            pass
    else:
        clip = ImageClip(str(path)).set_duration(duration)
        try:
            clip = clip.resize(newsize=(ow, oh))
        except Exception:
            pass
    return _soft_fade(clip, major, 0.08)


def _ken_burns_clip(
    mods: dict,
    path: Path,
    duration: float,
    index: int,
    major: int,
    zoom_span: float = 0.18,
    out_size=(1920, 1080),
):
    """Still → fixed even frame. zoom_span=0 → sharp hold (preferred for faces)."""
    if float(zoom_span or 0) <= 0.01:
        return _hold_still_clip(mods, path, duration, major, out_size=out_size)
    ImageClip = mods["ImageClip"]
    ow, oh = int(out_size[0]) // 2 * 2, int(out_size[1]) // 2 * 2
    span = max(0.0, min(0.08, float(zoom_span or 0.05)))
    scale = 1.0 + (span if index % 2 == 0 else span * 0.4)

    if major >= 2:
        clip = ImageClip(str(path)).with_duration(duration)
        try:
            clip = clip.resized(new_size=(ow, oh))
        except Exception:
            pass
        if scale > 1.01:
            try:
                zw, zh = int(ow * scale) // 2 * 2, int(oh * scale) // 2 * 2
                clip = clip.resized(new_size=(zw, zh))
                clip = clip.resized(new_size=(ow, oh))
            except Exception:
                clip = _force_even_size(clip, major, (ow, oh))
        return _soft_fade(clip, major, 0.15)

    clip = ImageClip(str(path)).set_duration(duration)
    try:
        clip = clip.resize(newsize=(ow, oh))
    except Exception:
        pass
    return _soft_fade(clip, major, 0.15)


def build_video(
    image_paths: Sequence[str | Path],
    audio_path: str | Path | None,
    out_mp4: str | Path,
    duration_per_image: float = 4.0,
    *,
    fps: int = 30,
    bitrate: str = "8000k",
    crossfade_sec: float = 0.0,
    zoom_span: float = 0.10,
    out_size=(1920, 1080),
) -> Path:
    """Slideshow encode — chain concat (no negative-padding compose; that glitched ends)."""
    api = _moviepy_api()
    if api is None:
        raise RuntimeError("moviepy not installed. Run: pip install moviepy imageio-ffmpeg")

    mods, major = api
    concatenate_videoclips = mods["concatenate_videoclips"]
    AudioFileClip = mods["AudioFileClip"]
    paths = [Path(p) for p in image_paths if p and Path(p).is_file()]
    if not paths:
        raise ValueError("need at least one image")
    out = Path(out_mp4)
    out.parent.mkdir(parents=True, exist_ok=True)
    dur = max(2.4, float(duration_per_image or 4.0))
    ow = int(out_size[0]) // 2 * 2
    oh = int(out_size[1]) // 2 * 2

    clips = [
        _ken_burns_clip(mods, p, dur, i, major, zoom_span=zoom_span, out_size=(ow, oh))
        for i, p in enumerate(paths)
    ]
    # method=chain is stable; compose+negative padding caused rainbow end corruption
    video = concatenate_videoclips(clips, method="chain")
    video = _force_even_size(video, major, (ow, oh))
    audio_clip = None
    if audio_path and Path(audio_path).is_file():
        audio_clip = AudioFileClip(str(audio_path))
        try:
            aud_dur = float(audio_clip.duration or 0)
            vid_dur = float(video.duration or 0)
        except Exception:
            aud_dur, vid_dur = 0.0, 0.0
        if aud_dur > 0 and aud_dur > vid_dur + 0.3 and clips:
            # Stretch last still cleanly instead of leaving silent/corrupt tail
            extra = aud_dur - vid_dur
            last = clips[-1]
            try:
                if major >= 2:
                    hold = last.with_duration(float(last.duration) + extra)
                else:
                    hold = last.set_duration(float(last.duration) + extra)
                clips = list(clips[:-1]) + [hold]
                _safe_close_many(video)
                video = concatenate_videoclips(clips, method="chain")
                video = _force_even_size(video, major, (ow, oh))
            except Exception:
                pass
        video, audio_clip = _sync_audio(video, audio_clip, major)

    video = _force_even_size(video, major, (ow, oh))
    try:
        _write_mp4(video, out, fps=fps, bitrate=bitrate)
    finally:
        _safe_close_many(video, audio_clip, *clips)

    if not out.is_file() or out.stat().st_size < 1000:
        raise RuntimeError(f"video write failed: {out}")
    return out.resolve()


def build_vlog_video(
    clip_paths: Sequence[str | Path],
    audio_path: str | Path | None,
    out_mp4: str | Path,
    *,
    fps: int = 30,
    bitrate: str = "8000k",
    out_size=(1080, 1920),
    seconds_per_clip: float | None = None,
) -> Path:
    """Real motion clips + VO — Instagram day-in-the-life style (not still slideshow)."""
    api = _moviepy_api()
    if api is None:
        raise RuntimeError("moviepy not installed. Run: pip install moviepy imageio-ffmpeg")
    mods, major = api
    VideoFileClip = mods.get("VideoFileClip")
    if VideoFileClip is None:
        raise RuntimeError("moviepy VideoFileClip unavailable")
    concatenate_videoclips = mods["concatenate_videoclips"]
    AudioFileClip = mods["AudioFileClip"]

    paths = [Path(p) for p in clip_paths if p and Path(p).is_file()]
    if not paths:
        raise ValueError("need at least one video clip")
    out = Path(out_mp4)
    out.parent.mkdir(parents=True, exist_ok=True)
    ow = int(out_size[0]) // 2 * 2
    oh = int(out_size[1]) // 2 * 2

    audio_clip = None
    aud_dur = 0.0
    if audio_path and Path(audio_path).is_file():
        audio_clip = AudioFileClip(str(audio_path))
        try:
            aud_dur = float(audio_clip.duration or 0)
        except Exception:
            aud_dur = 0.0

    n = len(paths)
    if seconds_per_clip and seconds_per_clip > 0:
        per = max(2.5, float(seconds_per_clip))
    elif aud_dur > 0:
        per = max(2.8, aud_dur / n)
    else:
        per = 4.0

    built = []
    raw_clips = []
    for i, p in enumerate(paths):
        raw = VideoFileClip(str(p))
        raw_clips.append(raw)
        try:
            src_dur = float(raw.duration or per)
        except Exception:
            src_dur = per
        take = min(per, max(2.0, src_dur - 0.05))
        # Prefer middle of clip (less logo/intro junk)
        start = 0.0
        if src_dur > take + 0.8:
            start = max(0.0, (src_dur - take) * 0.25)
        try:
            if major >= 2 and hasattr(raw, "subclipped"):
                piece = raw.subclipped(start, start + take)
            else:
                piece = raw.subclip(start, start + take)
        except Exception:
            piece = raw
        try:
            if major >= 2 and hasattr(piece, "without_audio"):
                piece = piece.without_audio()
            elif hasattr(piece, "without_audio"):
                piece = piece.without_audio()
            else:
                piece = piece.set_audio(None) if hasattr(piece, "set_audio") else piece
        except Exception:
            pass
        piece = _fit_clip(piece, major, ow, oh)
        piece = _soft_fade(piece, major, 0.18)
        built.append(piece)

    video = concatenate_videoclips(built, method="chain")
    video = _force_even_size(video, major, (ow, oh))

    # If VO longer than clips, loop clips to cover narration
    try:
        vdur = float(video.duration or 0)
    except Exception:
        vdur = 0.0
    if aud_dur > 0 and vdur > 0 and aud_dur > vdur + 0.5:
        loops_needed = int(aud_dur / vdur) + 1
        loops_needed = max(1, min(4, loops_needed))
        if loops_needed > 1:
            _safe_close_many(video)
            video = concatenate_videoclips(built * loops_needed, method="chain")
            video = _force_even_size(video, major, (ow, oh))

    video, audio_clip = _sync_audio(video, audio_clip, major)
    video = _force_even_size(video, major, (ow, oh))
    try:
        _write_mp4(video, out, fps=fps, bitrate=bitrate)
    finally:
        _safe_close_many(video, audio_clip, *built, *raw_clips)

    if not out.is_file() or out.stat().st_size < 1000:
        raise RuntimeError(f"vlog video write failed: {out}")
    return out.resolve()


def build_synced_beats(
    beats: Sequence[dict[str, Any]],
    out_mp4: str | Path,
    *,
    fps: int = 30,
    bitrate: str = "8000k",
    out_size=(1080, 1920),
) -> Path:
    """One visual + one VO line per beat — speech matches what is on screen.

    Each beat dict:
      visual: path to image or video
      audio: path to mp3 for that line
      kind: "face" | "broll" (optional)
    """
    api = _moviepy_api()
    if api is None:
        raise RuntimeError("moviepy not installed. Run: pip install moviepy imageio-ffmpeg")
    mods, major = api
    AudioFileClip = mods["AudioFileClip"]
    VideoFileClip = mods.get("VideoFileClip")
    concatenate_videoclips = mods["concatenate_videoclips"]

    out = Path(out_mp4)
    out.parent.mkdir(parents=True, exist_ok=True)
    ow = int(out_size[0]) // 2 * 2
    oh = int(out_size[1]) // 2 * 2

    segments = []
    raw_hold: list[Any] = []
    audio_hold: list[Any] = []

    for i, beat in enumerate(beats):
        if not isinstance(beat, dict):
            continue
        vis = Path(str(beat.get("visual") or ""))
        aud = Path(str(beat.get("audio") or ""))
        if not vis.is_file():
            continue
        kind = str(beat.get("kind") or "").lower()
        is_video = vis.suffix.lower() in (".mp4", ".mov", ".webm", ".mkv") or kind == "broll"

        aud_dur = 3.2
        audio_clip = None
        if aud.is_file():
            audio_clip = AudioFileClip(str(aud))
            audio_hold.append(audio_clip)
            try:
                aud_dur = max(1.6, float(audio_clip.duration or 3.2))
            except Exception:
                aud_dur = 3.2
        # Tiny pad so last syllable isn't cut
        take = aud_dur + 0.12

        if is_video and VideoFileClip is not None:
            raw = VideoFileClip(str(vis))
            raw_hold.append(raw)
            try:
                src_dur = float(raw.duration or take)
            except Exception:
                src_dur = take
            # Loop short stock clips to cover the spoken line
            pieces = []
            filled = 0.0
            while filled < take - 0.05:
                chunk = min(take - filled, max(0.8, src_dur - 0.08))
                start = 0.0
                if src_dur > chunk + 0.6:
                    start = min(src_dur - chunk - 0.05, (src_dur - chunk) * 0.2)
                try:
                    if major >= 2 and hasattr(raw, "subclipped"):
                        piece = raw.subclipped(start, start + chunk)
                    else:
                        piece = raw.subclip(start, start + chunk)
                except Exception:
                    piece = raw
                try:
                    if hasattr(piece, "without_audio"):
                        piece = piece.without_audio()
                except Exception:
                    pass
                pieces.append(piece)
                filled += chunk
                if src_dur < 1.2:
                    break
            if len(pieces) > 1:
                clip = concatenate_videoclips(pieces, method="chain")
            else:
                clip = pieces[0] if pieces else raw
            # Hard trim to narration length
            try:
                if major >= 2 and hasattr(clip, "subclipped"):
                    clip = clip.subclipped(0, take)
                else:
                    clip = clip.subclip(0, take)
            except Exception:
                pass
        else:
            # Locked character / campus still — sharp hold (no trashy zoom)
            src = str(beat.get("source") or kind or "")
            zoom = 0.0 if src in ("face", "scene", "") else 0.04
            clip = _ken_burns_clip(mods, vis, take, i, major, zoom_span=zoom, out_size=(ow, oh))

        clip = _fit_clip(clip, major, ow, oh)
        clip = _soft_fade(clip, major, 0.12)
        if audio_clip is not None:
            try:
                if major >= 2:
                    clip = clip.with_audio(audio_clip)
                else:
                    clip = clip.set_audio(audio_clip)
            except Exception:
                pass
        heading = str(beat.get("heading") or "").strip()
        if heading:
            clip = _overlay_heading(clip, heading, mods, major, ow, oh, raw_hold)
        segments.append(clip)

    if not segments:
        raise ValueError("no synced beats to assemble")

    video = concatenate_videoclips(segments, method="chain")
    video = _force_even_size(video, major, (ow, oh))
    # Final trim safety — avoid corrupt tail frame
    try:
        vdur = float(video.duration or 0)
        if vdur > 0.1:
            if major >= 2 and hasattr(video, "subclipped"):
                video = video.subclipped(0, max(0.1, vdur - 0.04))
            elif hasattr(video, "subclip"):
                video = video.subclip(0, max(0.1, vdur - 0.04))
    except Exception:
        pass
    video = _force_even_size(video, major, (ow, oh))
    try:
        _write_mp4(video, out, fps=fps, bitrate=bitrate)
    finally:
        _safe_close_many(video, *segments, *audio_hold, *raw_hold)

    if not out.is_file() or out.stat().st_size < 1000:
        raise RuntimeError(f"synced beat video write failed: {out}")
    return out.resolve()


def run_image(topic: str, *, style: str = "cinematic", width: int = 1280, height: int = 720) -> dict[str, Any]:
    topic_clean = re.sub(r"\s+", " ", (topic or "").strip())
    if not topic_clean:
        return {"ok": False, "status": "error", "message": "topic is required"}
    root = out_root()
    # Prefer one Pexels still when configured
    try:
        from jarvis.mira import pexels as pexels_mod

        if pexels_mod.configured():
            orient = "portrait" if height > width else "landscape"
            paths, credits = pexels_mod.fetch_stills(
                topic_clean, root / "images", count=1, orientation=orient
            )
            if paths:
                path = _upscale_sharpen(
                    paths[0],
                    1920 if width >= height else 1080,
                    1080 if width >= height else 1920,
                )
                note = pexels_mod.attribution_line(credits)
                return {
                    "ok": True,
                    "status": "ok",
                    "action": "create_image",
                    "image_path": str(path),
                    "provider": "pexels",
                    "credits": credits,
                    "message": f"Image ready: {path.name}. {note}",
                }
    except Exception as exc:
        logger.warning("Pexels image failed: %s", exc)

    dest = root / "images" / f"{_stem(topic_clean, 'img')}.jpg"
    try:
        path = generate_still(
            enhance_still_prompt(topic_clean, style=style),
            dest,
            width=width,
            height=height,
        )
        path = _upscale_sharpen(
            path,
            1920 if width >= height else 1080,
            1080 if width >= height else 1920,
        )
    except Exception as exc:
        return {"ok": False, "status": "error", "message": str(exc)[:240]}
    return {
        "ok": True,
        "status": "ok",
        "action": "create_image",
        "image_path": str(path),
        "provider": "pollinations+mira_v2",
        "message": f"Image ready: {path.name}",
    }


def run_video(
    topic: str,
    *,
    script: str | None = None,
    duration_sec: int = 30,
    n_stills: int | None = None,
    aspect: str = "16:9",
    style: str = "cinematic",
    voice: str | None = None,
    audio_mode: str = "voice",
    media_paths: list[str] | None = None,
    use_uploads: bool = False,
    search_hints: list[str] | None = None,
    force_character: bool = False,
    mood: str | None = None,
    fit_mode: str | None = None,
) -> dict[str, Any]:
    """Plan → make → verify → fix. Never deliver random/off-brief as success."""
    from jarvis.mira.agent_loop import run_with_verify
    from jarvis.mira.last_output import save_last_output

    topic_clean = re.sub(r"\s+", " ", (topic or "").strip())
    if not topic_clean:
        return {"ok": False, "status": "error", "message": "topic is required"}

    brief = (script or topic_clean).strip() or topic_clean

    # HARD LOCK: known sites + any web product/API/SaaS → live screen-record ONLY.
    # Never invent Pexels/AI portraits or cinematic B-roll for a real product ask.
    try:
        from jarvis.mira.platforms import detect_platform, run_platform_tour

        plat = detect_platform(topic_clean) or detect_platform(brief) or detect_platform(
            f"{topic_clean} {brief}"
        )
        if not plat:
            try:
                from jarvis.mira.web_products import looks_like_web_product_ask, resolve_web_product

                ask_blob = f"{topic_clean} {brief}".strip()
                if looks_like_web_product_ask(ask_blob) or looks_like_web_product_ask(topic_clean):
                    plat = resolve_web_product(ask_blob) or resolve_web_product(topic_clean)
            except Exception:
                pass
        if plat:
            try:
                from jarvis.tools.mira_jobs import set_progress

                set_progress(
                    f"Watch Chrome — recording live {plat['name']} (not stock scenes)…"
                )
            except Exception:
                pass
            tour_ask = topic_clean if detect_platform(topic_clean) else brief
            # Ensure "video" intent so wants_platform_record stays true inside tour helpers
            if not re.search(r"\b(video|clip|reel|short|tour|explore)\b", tour_ask, re.I):
                tour_ask = f"full video of {tour_ask}"
            out = run_platform_tour(
                tour_ask,
                # Full tours are many minutes — never clamp to 90s metadata/budget
                duration_sec=max(45, int(duration_sec or 180)),
                aspect=aspect,
                voice=voice,
                audio_mode=audio_mode,
            )
            if out.get("ok"):
                try:
                    save_last_output(
                        {
                            **out,
                            "topic": topic_clean,
                            "mood": mood,
                            "aspect": aspect,
                            "format": "youtube_shorts" if str(aspect) == "9:16" else "youtube",
                            "duration_sec": duration_sec,
                        }
                    )
                except Exception:
                    pass
                return out
            return {
                "ok": False,
                "status": "error",
                "message": (
                    f"Could not screen-record {plat['name']} live. "
                    f"{(out.get('message') or 'Retry')[:160]} "
                    "Jarvis will not invent random stock scenes for this ask."
                )[:320],
                "notes": list(out.get("notes") or []) + ["platform_hard_lock=no_stock_fallback"],
                "provider": "mira_platform_required",
                "platform": plat["id"],
            }
    except Exception as exc:
        # Still refuse stock for named platforms
        try:
            from jarvis.mira.platforms import detect_platform

            if detect_platform(topic_clean) or detect_platform(brief):
                return {
                    "ok": False,
                    "status": "error",
                    "message": f"Platform tour crashed: {exc}"[:240],
                    "notes": ["platform_hard_lock=exception"],
                }
        except Exception:
            pass

    def _once(**kw: Any) -> dict[str, Any]:
        return _run_video_once(
            kw.get("topic") or topic_clean,
            script=kw.get("script", script),
            duration_sec=int(kw.get("duration_sec") or duration_sec),
            n_stills=n_stills,
            aspect=str(kw.get("aspect") or aspect),
            style=style,
            voice=voice,
            audio_mode=str(kw.get("audio_mode") or audio_mode),
            media_paths=kw.get("media_paths", media_paths),
            use_uploads=bool(kw.get("use_uploads", use_uploads)),
            search_hints=kw.get("search_hints", search_hints),
            force_character=bool(kw.get("force_character", force_character)),
            mood=kw.get("mood", mood),
            fit_mode=kw.get("fit_mode", fit_mode),
        )

    out = run_with_verify(
        brief,
        _once,
        max_attempts=2,  # fidelity: retry once if off-brief
        make_kwargs={
            "topic": topic_clean,
            "script": script,
            "duration_sec": duration_sec,
            "aspect": aspect,
            "audio_mode": audio_mode,
            "media_paths": media_paths,
            "use_uploads": use_uploads,
            "search_hints": search_hints,
            "force_character": force_character,
            "mood": mood,
            "fit_mode": fit_mode,
        },
    )
    if out.get("ok"):
        try:
            save_last_output({
                **out,
                "topic": topic_clean,
                "mood": mood,
                "aspect": aspect,
                "format": "youtube_shorts" if str(aspect) == "9:16" else "youtube",
                "duration_sec": duration_sec,
            })
        except Exception:
            pass
    return out


def _run_video_once(
    topic: str,
    *,
    script: str | None = None,
    duration_sec: int = 30,
    n_stills: int | None = None,
    aspect: str = "16:9",
    style: str = "cinematic",
    voice: str | None = None,
    audio_mode: str = "voice",
    media_paths: list[str] | None = None,
    use_uploads: bool = False,
    search_hints: list[str] | None = None,
    force_character: bool = False,
    mood: str | None = None,
    fit_mode: str | None = None,
) -> dict[str, Any]:
    """Single attempt: uploads → character → stock → stills."""
    from jarvis.mira.brief_match import needs_fantasy_characters

    topic_clean = re.sub(r"\s+", " ", (topic or "").strip())
    if not topic_clean:
        return {"ok": False, "status": "error", "message": "topic is required"}

    dur = max(12, min(90, int(duration_sec or 30)))
    mode = (audio_mode or "voice").strip().lower()
    if mode not in ("voice", "ambient", "both", "mute"):
        mode = "voice"
    brief = (script or topic_clean).strip() or topic_clean
    hints = [re.sub(r"\s+", " ", str(h).strip())[:80] for h in (search_hints or []) if str(h).strip()]
    mood_key = (mood or "").strip().lower() or None

    # Expand thin brands into real scenes before stock/AI (google ≠ letter stamps)
    prefer_ai_stills = False
    prefer_platform = False
    try:
        from jarvis.mira.intent import expand_ask

        ex = expand_ask(brief or topic_clean)
        prefer_ai_stills = bool(ex.get("prefer_ai_stills"))
        prefer_platform = bool(ex.get("prefer_platform_record"))
        for q in ex.get("search_queries") or []:
            q = re.sub(r"\s+", " ", str(q).strip())[:80]
            if q and q not in hints:
                hints.append(q)
        # Keep VO/topic as original ask; search uses expanded hints
        if ex.get("_via") == "entity_expand" and ex.get("original"):
            # Motion search uses expanded queries; verify against original entity
            pass
    except Exception:
        pass

    # 1) User media only when explicitly requested
    if use_uploads or media_paths:
        user_out = _run_video_user_media(
            topic_clean,
            script=script,
            duration_sec=dur,
            aspect=aspect,
            voice=voice,
            audio_mode=mode,
            media_paths=media_paths,
            use_uploads=bool(use_uploads),
            fit_mode=fit_mode,
        )
        if user_out.get("ok"):
            return user_out
        if use_uploads or media_paths:
            return user_out

    # 2) Real platform / product screen-record FIRST (before character or stock).
    # User asked for the site itself — do NOT invent random portraits / B-roll.
    notes: list[str] = []
    try:
        from jarvis.mira.platforms import detect_platform, run_platform_tour, wants_platform_record

        ask_text = brief or topic_clean
        plat = detect_platform(ask_text) or detect_platform(topic_clean)
        if not plat and prefer_platform:
            try:
                from jarvis.mira.web_products import resolve_web_product

                plat = resolve_web_product(ask_text) or resolve_web_product(topic_clean)
            except Exception:
                pass
        if plat and (prefer_platform or wants_platform_record(ask_text)):
            try:
                from jarvis.tools.mira_jobs import set_progress

                set_progress(f"Recording live {plat['name']} — not stock scenes…")
            except Exception:
                pass
            # Full product tours need headroom — do not clamp to Shorts 90s here
            tour_dur = max(dur, 120) if prefer_platform else dur
            plat_out = run_platform_tour(
                ask_text if detect_platform(ask_text) else topic_clean,
                duration_sec=tour_dur,
                aspect=aspect,
                voice=voice,
                audio_mode=mode,
            )
            if plat_out.get("ok"):
                return plat_out
            # HARD: never fall through to Pexels/AI stills for a named platform
            return {
                "ok": False,
                "status": "error",
                "message": (
                    f"Could not screen-record {plat['name']} live. "
                    f"{(plat_out.get('message') or 'Retry')[:160]} "
                    "Will not invent random stock scenes."
                )[:320],
                "notes": list(plat_out.get("notes") or [])
                + ["platform_hard_lock=no_stock_in__run_video_once"],
                "provider": "mira_platform_required",
                "platform": plat["id"],
            }
    except Exception as exc:
        try:
            from jarvis.mira.platforms import detect_platform

            if (
                prefer_platform
                or detect_platform(brief or topic_clean)
                or detect_platform(topic_clean)
            ):
                return {
                    "ok": False,
                    "status": "error",
                    "message": f"Platform tour crashed: {exc}"[:240],
                    "notes": ["platform_hard_lock=exception_once"],
                }
        except Exception:
            pass
        notes.append(f"platform_record_error: {exc}")

    # 3) Talking / fantasy exact-brief path (fruits talking, etc.) — never for products
    if force_character or needs_fantasy_characters(brief):
        char_out = _run_video_character_dialogue(
            topic_clean,
            script=script,
            duration_sec=dur,
            aspect=aspect,
            voice=voice,
            audio_mode=mode if mode != "ambient" else "voice",
            mood=mood_key,
        )
        if char_out.get("ok"):
            return char_out
        return {
            "ok": False,
            "status": "error",
            "message": char_out.get("message")
            or "Could not build the exact talking-character video you asked for. Retry in a minute.",
            "notes": list(char_out.get("notes") or []),
            "brief_match": char_out.get("brief_match"),
        }

    # 3) Stock HD motion — skip for thin brands (Pexels "google" → letter stamps)
    motion: dict[str, Any] = {"ok": False, "message": "skipped", "notes": []}
    if prefer_ai_stills:
        notes.append("skip_motion_prefer_ai_brand")
    else:
        motion = _run_video_motion_fast(
            topic_clean,
            script=script,
            duration_sec=dur,
            aspect=aspect,
            voice=voice,
            audio_mode=mode,
            search_hints=hints or None,
            mood=mood_key,
        )
        if motion.get("ok"):
            from jarvis.mira.brief_match import output_match_score

            m = output_match_score(brief, list(motion.get("beats") or []))
            motion["brief_match"] = m
            if not m.get("ok"):
                # Let agent_loop retry with tighter hints — mark as soft fail
                motion["ok"] = False
                motion["status"] = "error"
                motion["message"] = (
                    f"Brief mismatch (score={m.get('score')}). "
                    f"Missing: {', '.join(m.get('missing') or [])}"
                )[:280]
                return motion
            return motion
        notes.extend(list(motion.get("notes") or []))
        notes.append(f"motion_path_skipped: {motion.get('message') or 'fallback'}")

    # Exact-brief stills — AI for brands (+ Pexels fill), filtered Pexels otherwise
    stills = _run_video_stills_fallback(
        topic_clean,
        script=script,
        duration_sec=dur,
        n_stills=n_stills,
        aspect=aspect,
        style=style,
        voice=voice,
        notes=notes,
        prefer_ai=prefer_ai_stills,
        audio_mode=mode,
    )
    if stills.get("ok"):
        stills.setdefault("notes", notes)
        return stills

    return {
        "ok": False,
        "status": "error",
        "message": motion.get("message")
        or stills.get("message")
        or "Could not assemble an on-topic video. Try a clearer topic.",
        "notes": list(stills.get("notes") or notes),
        "brief_match": motion.get("brief_match") or stills.get("brief_match"),
    }


def _run_video_character_dialogue(
    topic: str,
    *,
    script: str | None,
    duration_sec: int,
    aspect: str,
    voice: str | None,
    audio_mode: str,
    mood: str | None = None,
) -> dict[str, Any]:
    """Talking-subject video: HD stock motion + dialogue VO (gold quality).

    Soft melted AI faces caused trashy output. Default is photographic Pexels
    clips of each speaker subject + conversation VO. Cartoon AI faces only if
    the user asks for cartoon/pixar/animated.
    """
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from jarvis.mira import pexels as pexels_mod
    from jarvis.mira.brief_match import (
        output_match_score,
        plan_match_score,
        wants_cartoon_style,
    )
    from jarvis.mira.director import _heuristic_plan, plan_video
    from jarvis.mira.fast_encode import build_fast_synced_beats

    t0 = time.perf_counter()
    cartoon = wants_cartoon_style(f"{topic} {script or ''}")
    notes: list[str] = [
        "mode=dialogue_hd_stock_v9" if not cartoon else "mode=dialogue_cartoon_ai_v9",
    ]
    if duration_sec <= 18:
        n = 2
    elif duration_sec >= 40:
        n = 4
    else:
        n = 3
    plan = plan_video(
        topic,
        n_beats=n,
        duration_sec=duration_sec,
        audio_mode=audio_mode,
        user_script=script,
        force_character=True,
        mood=mood,
    )
    match = plan.get("_match") or plan_match_score(topic, plan)
    notes.append(f"plan_match={match}")
    if not match.get("ok"):
        plan = _heuristic_plan(topic, n, character=True, mood=mood)
        match = plan_match_score(topic, plan)
        plan["_match"] = match
        notes.append(f"plan_rematch={match}")
    if not match.get("ok"):
        return {
            "ok": False,
            "status": "error",
            "message": (
                f"Could not plan a brief-matching video for: {topic}. "
                f"Missing: {', '.join(match.get('missing') or [])}"
            )[:280],
            "notes": notes,
            "brief_match": match,
        }

    beats_plan = list(plan.get("beats") or [])[:n]
    vertical = aspect in ("9:16", "vertical", "shorts", "reel")
    out_w, out_h = (1080, 1920) if vertical else (1920, 1080)
    orient = "portrait" if vertical else "landscape"
    root = out_root()
    clips_dir = root / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    img_dir = root / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    audio_dir = root / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    # Parallel fetch HD clips for each speaker subject
    queries: list[str] = []
    for b in beats_plan:
        sp = str(b.get("speaker") or "").strip() or "subject"
        q = str(b.get("query") or "").strip()
        if not q or "character" in q.lower():
            q = f"{sp.lower()} fruit close up cinematic" if "fruit" in topic.lower() else f"{sp.lower()} close up cinematic"
        queries.append(q)

    fetched: list[tuple[str, list[Path], list]] = []
    if not cartoon and pexels_mod.configured():
        fetched = pexels_mod.fetch_videos_parallel(
        queries, clips_dir, orientation=orient, max_workers=min(5, n), brief=topic
    )
        notes.append(f"pexels_parallel={len(fetched)}")
    else:
        notes.append("pexels_skipped_cartoon_or_unconfigured")

    synced: list[dict[str, Any]] = []
    vo_jobs: list[tuple[int, str, Path]] = []
    credits: list[dict[str, Any]] = []

    for i, b in enumerate(beats_plan):
        speaker = str(b.get("speaker") or "").strip()
        line = str(b.get("line") or "").strip()
        if speaker and line and not re.match(rf"^{re.escape(speaker)}\b", line, re.I):
            spoken = f"{speaker} says: {line}"
        else:
            spoken = line or topic
        heading = re.sub(r"[^A-Za-z0-9 ]", "", str(b.get("heading") or speaker or f"BEAT {i+1}"))[:28]
        visual: Path | None = None
        source = "pexels"
        entry_pexels_url = ""
        entry_rel: dict[str, Any] | None = None

        if not cartoon and i < len(fetched):
            _q, paths, creds = fetched[i]
            if paths:
                cred0 = creds[0] if creds else {}
                rel = cred0.get("relevance") if isinstance(cred0, dict) else None
                if isinstance(rel, dict) and not rel.get("ok"):
                    notes.append(f"reject_visual_char:{_q[:40]}")
                else:
                    visual = paths[0]
                    credits.extend(creds)
                    entry_pexels_url = str(cred0.get("pexels_url") or "")
                    entry_rel = rel if isinstance(rel, dict) else None

        # Cartoon / AI face path only when requested — with quality gate
        if visual is None and cartoon:
            still_prompt = str(b.get("still_prompt") or "").strip() or (
                f"expressive {speaker or 'character'} face mid-speech, clear eyes and mouth, "
                f"Pixar-quality stylized, sharp focus, studio softbox"
            )
            # Faces: prioritize readable features over soft melted AI look
            still_prompt = (
                f"{still_prompt}, ultra sharp face, coherent eyes mouth nose, "
                f"no melt, no blur, no extra limbs, no watermark, no text, 8k detail"
            )[:480]
            img_path = img_dir / f"{_stem(f'char_{topic[:20]}_{i}', 'img')}.jpg"
            try:
                generate_still(
                    still_prompt,
                    img_path,
                    width=1280 if not vertical else 768,
                    height=720 if not vertical else 1280,
                    model="flux",
                    enhance=True,
                    raw=True,
                    max_attempts=4,
                    timeout=90.0,
                )
                if img_path.stat().st_size < 80_000:
                    raise RuntimeError("AI still too small/soft")
                hq = _upscale_sharpen(img_path, target_w=out_w, target_h=out_h)
                visual = hq if hq.is_file() else img_path
                source = "pollinations_flux"
            except Exception as exc:
                notes.append(f"ai still reject {i}: {exc}")

        # Final fallback: Pexels photo still of the subject (sharp stock)
        if visual is None and pexels_mod.configured():
            try:
                paths, creds = pexels_mod.fetch_stills(
                    queries[i] if i < len(queries) else speaker or topic,
                    img_dir,
                    count=1,
                    orientation=orient,
                )
                if paths:
                    visual = paths[0]
                    credits.extend(creds)
                    source = "pexels_still"
            except Exception as exc:
                notes.append(f"pexels still fail {i}: {exc}")

        if visual is None or not Path(visual).is_file():
            notes.append(f"beat {i}: no visual")
            continue

        entry = {
            "tag": f"c{i}",
            "kind": "character",
            "source": source,
            "visual": str(visual),
            "audio": "",
            "line": spoken,
            "heading": heading,
            "speaker": speaker,
            "query": queries[i] if i < len(queries) else "",
            "pexels_url": entry_pexels_url,
            "relevance": entry_rel,
        }
        dest = audio_dir / f"{_stem(f'char_{topic[:20]}_{i}', 'vo')}.mp3"
        vo_jobs.append((len(synced), spoken, dest))
        synced.append(entry)

    if len(synced) < (2 if duration_sec <= 18 else 3):
        need = 2 if duration_sec <= 18 else 3
        return {
            "ok": False,
            "status": "error",
            "message": f"Need ≥{need} dialogue beats with visuals, got {len(synced)}",
            "notes": notes,
        }

    def _vo(job: tuple[int, str, Path]) -> tuple[int, str | None]:
        idx, line, dest = job
        try:
            return idx, str(generate_voiceover(line, dest, voice=voice))
        except Exception as exc:
            notes.append(f"VO fail: {exc}")
            return idx, None

    with ThreadPoolExecutor(max_workers=min(5, len(vo_jobs))) as pool:
        for fut in as_completed([pool.submit(_vo, j) for j in vo_jobs]):
            idx, path = fut.result()
            if path:
                synced[idx]["audio"] = path
    synced = [s for s in synced if s.get("audio")] or synced

    out_match = output_match_score(topic, synced)
    notes.append(f"output_match={out_match}")
    if not out_match.get("ok"):
        return {
            "ok": False,
            "status": "error",
            "message": (
                f"Generated plan did not match your ask closely enough "
                f"(score={out_match.get('score')}). Missing: "
                f"{', '.join(out_match.get('missing') or [])}"
            )[:300],
            "notes": notes,
            "brief_match": out_match,
            "beats": synced,
        }

    if credits:
        try:
            notes.append(pexels_mod.attribution_line(credits))
        except Exception:
            pass

    out_path = root / "videos" / f"{_stem(f'talk_{topic}', 'vid')}.mp4"
    try:
        video_path = build_fast_synced_beats(
            synced,
            out_path,
            fps=30,
            bitrate="16000k",
            out_size=(out_w, out_h),
            audio_mode="voice",
        )
    except Exception as exc:
        return {"ok": False, "status": "error", "message": str(exc)[:240], "notes": notes}

    # Quality gate: reject tiny soft outputs
    try:
        size = Path(video_path).stat().st_size
    except Exception:
        size = 0
    if size < 3_000_000:
        return {
            "ok": False,
            "status": "error",
            "message": f"Quality gate failed — output too small ({size} bytes). Retry.",
            "notes": notes,
            "video_path": str(video_path),
        }

    elapsed = time.perf_counter() - t0
    return {
        "ok": True,
        "status": "ok",
        "action": "create_video",
        "topic": topic,
        "script": " ".join(s.get("line") or "" for s in synced),
        "video_path": str(video_path),
        "beats": synced,
        "duration_sec": duration_sec,
        "aspect": "9:16" if vertical else "16:9",
        "audio_mode": "voice",
        "provider": (
            "mira_jarvis_v8_dialogue_hd_stock"
            if not cartoon
            else "mira_jarvis_v8_dialogue_cartoon"
        ),
        "still_source": "pexels_video" if not cartoon else "pollinations_flux",
        "elapsed_sec": round(elapsed, 1),
        "brief_match": out_match,
        "plan_title": plan.get("title"),
        "director": plan.get("_director"),
        "mira_engine": True,
        "is_trained_foundation_model": False,
        "message": (
            f"Video ready in {elapsed:.0f}s (dialogue · HD): {Path(video_path).name} "
            f"· match {out_match.get('score')}"
        ),
        "notes": notes,
        "learning_note": "Rate this with mira_rate to improve future quality.",
    }


def _run_video_user_media(
    topic: str,
    *,
    script: str | None,
    duration_sec: int,
    aspect: str,
    voice: str | None,
    audio_mode: str,
    media_paths: list[str] | None,
    use_uploads: bool,
    fit_mode: str | None = None,
) -> dict[str, Any]:
    """Assemble a video from the user's uploaded / provided clips & images."""
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from jarvis.mira import uploads as uploads_mod
    from jarvis.mira.fast_encode import build_fast_synced_beats

    t0 = time.perf_counter()
    # Uploads default to contain so nothing is silently cropped
    fit = (fit_mode or "contain").strip().lower() or "contain"
    if fit in ("letterbox", "pad", "fit", "full"):
        fit = "contain"
    notes: list[str] = [f"audio_mode={audio_mode}", "mode=user_media_v9_priority", f"fit_mode={fit}"]
    paths = uploads_mod.resolve_media_paths(
        list(media_paths or []),
        use_uploads=use_uploads,
        limit=8 if duration_sec >= 35 else (6 if duration_sec >= 22 else 4),
    )
    if len(paths) < 1:
        return {
            "ok": False,
            "status": "error",
            "message": (
                "No user media found. Upload via HUD (Mira Upload) or drop files in "
                "data/mira/uploads, then say what video you want."
            ),
            "notes": notes,
        }

    n = min(len(paths), 6 if duration_sec >= 30 else (4 if duration_sec >= 18 else 3))
    paths = paths[:n]
    from jarvis.mira.brief_match import needs_fantasy_characters, plan_match_score
    from jarvis.mira.director import plan_video

    brief = (script or topic).strip() or topic
    # Exact ask: VO/headings from YOUR words — do not invent a different story
    parts = re.split(r"(?<=[.!?])\s+|\n+", brief)
    parts = [p.strip() for p in parts if p.strip()]
    if len(parts) < n:
        # Repeat / slice topic so every beat still says the ask
        base = brief[:120] if brief else topic
        while len(parts) < n:
            parts.append(base)
    lines = [parts[i][:180] for i in range(n)]
    headings = [f"CLIP {i + 1}" for i in range(n)]
    director_name = "brief_exact"
    # Optional director only for heading polish — never override lines if mismatch
    try:
        from jarvis.mira.brief_match import plan_match_score
        from jarvis.mira.director import plan_video

        plan = plan_video(
            brief,
            n_beats=n,
            duration_sec=duration_sec,
            audio_mode=audio_mode,
            user_script=brief,
            force_character=False,
        )
        pm = plan_match_score(brief, plan)
        notes.append(f"plan_match={pm}")
        director_name = str(plan.get("_director") or "heuristic")
        notes.append(f"director={director_name}")
        beats_plan = list(plan.get("beats") or [])
        if pm.get("ok"):
            for i in range(n):
                if i < len(beats_plan):
                    h = str(beats_plan[i].get("heading") or "").strip()
                    if h:
                        headings[i] = h[:28]
                    # Keep line from brief; only fill if empty
                    if not lines[i] and beats_plan[i].get("line"):
                        lines[i] = str(beats_plan[i]["line"])[:180]
        else:
            notes.append("director_ignored_off_brief")
    except Exception as exc:
        notes.append(f"director_skip:{exc}")
    notes.append(f"user_media={n}")
    notes.append(f"videos={sum(1 for p in paths if uploads_mod.is_video(p))}")
    notes.append(f"images={sum(1 for p in paths if uploads_mod.is_image(p))}")
    notes.append("priority=user_uploads_exact_brief")

    vertical = aspect in ("9:16", "vertical", "shorts", "reel")
    out_w, out_h = (1080, 1920) if vertical else (1920, 1080)
    root = out_root()
    audio_dir = root / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    need_vo = audio_mode in ("voice", "both")
    synced: list[dict[str, Any]] = []
    vo_jobs: list[tuple[int, str, Path]] = []

    for i, vis in enumerate(paths):
        line = lines[i] if i < len(lines) else topic
        heading = headings[i] if i < len(headings) else ""
        tag = f"u{i}"
        entry: dict[str, Any] = {
            "tag": tag,
            "kind": "user",
            "source": "upload",
            "visual": str(vis),
            "audio": "",
            "line": line,
            "heading": heading,
        }
        if need_vo:
            dest = audio_dir / f"{_stem(f'user_{topic[:20]}_{tag}', 'vo')}.mp3"
            vo_jobs.append((len(synced), line, dest))
        synced.append(entry)

    if need_vo and vo_jobs:

        def _vo(job: tuple[int, str, Path]) -> tuple[int, str | None]:
            idx, line, dest = job
            try:
                return idx, str(generate_voiceover(line, dest, voice=voice))
            except Exception as exc:
                notes.append(f"VO fail: {exc}")
                return idx, None

        with ThreadPoolExecutor(max_workers=min(5, len(vo_jobs))) as pool:
            for fut in as_completed([pool.submit(_vo, j) for j in vo_jobs]):
                idx, path = fut.result()
                if path:
                    synced[idx]["audio"] = path
        if audio_mode == "voice":
            synced = [s for s in synced if s.get("audio")] or synced

    out_path = root / "videos" / f"{_stem(f'user_{topic}', 'vid')}.mp4"
    try:
        video_path = build_fast_synced_beats(
            synced,
            out_path,
            fps=30,
            bitrate="16000k",
            out_size=(out_w, out_h),
            audio_mode=audio_mode,
            fit_mode=fit,
        )
    except Exception as exc:
        return {
            "ok": False,
            "status": "error",
            "message": str(exc)[:240],
            "notes": notes,
            "beats": synced,
        }

    elapsed = time.perf_counter() - t0
    notes.append(f"elapsed_sec={elapsed:.1f}")
    vo_script = " ".join(s.get("line") or "" for s in synced)
    from jarvis.mira.brief_match import output_match_score

    out_match = output_match_score(topic, synced)
    notes.append(f"output_match={out_match}")

    # One-shot consume: don't reuse this batch on the next unrelated idea
    try:
        uploads_mod.clear_active_batch()
        notes.append("active_batch_cleared")
    except Exception:
        pass

    return {
        "ok": True,
        "status": "ok",
        "action": "create_video",
        "topic": topic,
        "script": vo_script,
        "video_path": str(video_path),
        "beats": synced,
        "user_media": [str(p) for p in paths],
        "duration_sec": duration_sec,
        "aspect": "9:16" if vertical else "16:9",
        "audio_mode": audio_mode,
        "provider": "mira_jarvis_v9_user_media",
        "still_source": "user_upload",
        "explicit_uploads": True,
        "elapsed_sec": round(elapsed, 1),
        "mira_engine": True,
        "is_trained_foundation_model": False,
        "director": director_name,
        "brief_match": out_match,
        "message": (
            f"Video ready in {elapsed:.0f}s from YOUR media: {video_path.name} "
            f"({n} clips · {audio_mode}) — uploads first."
        ),
        "notes": notes,
        "learning_note": "Rate this with mira_rate to improve future quality.",
    }


def _topic_queries(topic: str, n: int) -> list[str]:
    """Pexels-friendly search queries for an arbitrary user topic."""
    base = re.sub(r"\s+", " ", (topic or "cinematic scene").strip())[:80]
    # Strip filler words that hurt stock search
    base = re.sub(
        r"\b(make|create|generate|video|clip|about|please|a|an|the|of|for)\b",
        " ",
        base,
        flags=re.I,
    )
    base = re.sub(r"\s+", " ", base).strip() or "cinematic scene"
    suffixes = [
        "",
        "cinematic motion",
        "close up detail",
        "wide establishing",
        "atmosphere mood",
        "people lifestyle",
    ]
    out: list[str] = []
    for i in range(max(3, min(6, n))):
        suf = suffixes[i % len(suffixes)]
        q = f"{base} {suf}".strip() if suf else base
        out.append(q)
    return out


def _topic_beat_lines(topic: str, n: int, script: str | None = None) -> list[str]:
    """VO lines = the user's exact ask only. Never invent an explainer."""
    t = re.sub(r"\s+", " ", (topic or "").strip()) or "this scene"
    src = (script or "").strip() or t
    # Prefer real sentences from the user script / brief
    parts = re.split(r"(?<=[.!?])\s+|\n+|;\s*", src)
    parts = [p.strip() for p in parts if p.strip()]
    if len(parts) >= n:
        return [p[:160] for p in parts[:n]]
    if len(parts) == 1:
        # Thin brief ("google") → every beat says THAT, not coach filler
        return [parts[0][:160]] * n
    while len(parts) < n:
        parts.append(parts[-1] if parts else t)
    return [p[:160] for p in parts[:n]]


def _topic_headings(n: int) -> list[str]:
    labels = ["LOOK…", "FEEL", "DETAIL", "WIDE", "MOMENT", "CLOSE"]
    return [labels[i % len(labels)] for i in range(n)]


def _run_video_motion_fast(
    topic: str,
    *,
    script: str | None,
    duration_sec: int,
    aspect: str,
    voice: str | None,
    audio_mode: str,
    search_hints: list[str] | None = None,
    mood: str | None = None,
) -> dict[str, Any]:
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from jarvis.mira import pexels as pexels_mod
    from jarvis.mira.fast_encode import build_fast_synced_beats

    t0 = time.perf_counter()
    notes: list[str] = [f"audio_mode={audio_mode}", "mode=pexels_hd_fast_generic_v9_director"]
    if mood:
        notes.append(f"mood={mood}")
    if not pexels_mod.configured():
        return {"ok": False, "message": "PEXELS_API_KEY missing", "notes": notes}

    # Faster shorts: fewer beats for short duration (still real motion clips)
    if duration_sec <= 12:
        n = 2
    elif duration_sec <= 22:
        n = 2
    elif duration_sec >= 40:
        n = 4
    else:
        n = 3
    from jarvis.mira.director import plan_video

    plan = plan_video(
        topic,
        n_beats=n,
        duration_sec=duration_sec,
        audio_mode=audio_mode,
        user_script=script,
        mood=mood,
    )
    beats_plan = list(plan.get("beats") or [])
    n = max(2, min(4, len(beats_plan) or n))
    # Short Pexels-friendly queries rooted in the user topic (not long VO phrases)
    queries = []
    for b in beats_plan[:n]:
        raw_q = str(b.get("query") or topic).strip()
        variants = pexels_mod._pexels_query_variants(raw_q) or pexels_mod._pexels_query_variants(topic)
        queries.append((variants[0] if variants else raw_q)[:80])
    # Prefer GPT-understood search hints (messy user speech → concrete stock queries)
    hints = [h for h in (search_hints or []) if h]
    if hints:
        for i, h in enumerate(hints[:n]):
            variants = pexels_mod._pexels_query_variants(h) or [h]
            qh = variants[0][:80]
            if i < len(queries):
                queries[i] = qh
            else:
                queries.append(qh)
        notes.append(f"search_hints={hints[:4]}")
    # Ensure at least one beat searches the core topic itself
    core_vars = pexels_mod._pexels_query_variants(topic)
    if core_vars and queries:
        queries[0] = core_vars[0]
    # Inject topic nouns into every query for stricter match
    from jarvis.mira.brief_match import tokenize

    topic_toks = sorted(tokenize(topic), key=len, reverse=True)[:3]
    if topic_toks:
        for i, q in enumerate(queries):
            if not any(t in q.lower() for t in topic_toks):
                queries[i] = f"{topic_toks[0]} {q}"[:80]
    # VO = exact user ask only (director lines are often invented explainers)
    brief_for_vo = (script or topic).strip() or topic
    lines = _topic_beat_lines(topic, n, brief_for_vo)
    headings = [str(b.get("heading") or "") for b in beats_plan[:n]]
    notes.append(f"director={plan.get('_director') or 'unknown'}")
    notes.append(f"plan_title={plan.get('title') or topic}")
    notes.append(f"pexels_queries={queries}")
    notes.append("vo=exact_brief")
    notes.append(f"beats_target={n}")

    vertical = aspect in ("9:16", "vertical", "shorts", "reel")
    out_w, out_h = (1080, 1920) if vertical else (1920, 1080)
    orient = "portrait" if vertical else "landscape"
    root = out_root()
    clips_dir = root / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    audio_dir = root / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    fetched = pexels_mod.fetch_videos_parallel(
        queries,
        clips_dir,
        orientation=orient,
        max_workers=min(5, n),
        brief=topic,
    )
    notes.append(f"pexels_parallel={len(fetched)}")

    need_vo = audio_mode in ("voice", "both")
    synced: list[dict[str, Any]] = []
    credits: list[dict[str, Any]] = []
    vo_jobs: list[tuple[int, str, Path]] = []

    for i, (q, paths, creds) in enumerate(fetched):
        if not paths:
            notes.append(f"miss:{q[:40]}")
            continue
        cred0 = creds[0] if creds else {}
        rel = cred0.get("relevance") if isinstance(cred0, dict) else None
        # Drop off-brief clips — never narrate over random/office stock
        if isinstance(rel, dict) and not rel.get("ok"):
            notes.append(f"reject_visual:{q[:40]}:{rel.get('reason')}")
            continue
        if not rel:
            rel = pexels_mod.visual_relevance(
                topic,
                query=q,
                pexels_url=str(cred0.get("pexels_url") or ""),
                path=str(paths[0]),
            )
            if not rel.get("ok"):
                notes.append(f"reject_visual:{q[:40]}:{rel.get('reason')}")
                continue
        credits.extend(creds)
        line = lines[i] if i < len(lines) else topic
        heading = headings[i] if i < len(headings) else ""
        tag = f"b{i}"
        entry: dict[str, Any] = {
            "tag": tag,
            "kind": "broll",
            "source": "pexels",
            "visual": str(paths[0]),
            "audio": "",
            "line": line,
            "heading": heading,
            "query": q,
            "pexels_url": cred0.get("pexels_url") or "",
            "relevance": rel,
        }
        if need_vo:
            dest = audio_dir / f"{_stem(f'{topic[:24]}_{tag}', 'vo')}.mp3"
            vo_jobs.append((len(synced), line, dest))
        synced.append(entry)

    min_beats = 2 if int(duration_sec or 30) <= 22 else 3
    # Prefer duplicating ON-BRIEF clips over padding with random stock
    if synced and len(synced) < min_beats:
        base = list(synced)
        i = 0
        while len(synced) < min_beats and base:
            src = dict(base[i % len(base)])
            src["tag"] = f"dup{len(synced)}"
            # Fresh VO file path if needed
            if need_vo and src.get("line"):
                tag = str(src["tag"])
                dest = audio_dir / f"{_stem(f'{topic[:24]}_{tag}', 'vo')}.mp3"
                try:
                    generate_voiceover(str(src["line"]), dest, voice=voice)
                    src["audio"] = str(dest)
                except Exception:
                    src["audio"] = src.get("audio") or ""
            synced.append(src)
            i += 1
        notes.append(f"duplicated_on_brief_clips_to={len(synced)}")
    if len(synced) < min_beats:
        return {
            "ok": False,
            "message": (
                f"Could not find enough on-topic HD clips for “{topic}” "
                f"(got {len(synced)}, need {min_beats}). Try a clearer topic."
            ),
            "notes": notes,
        }

    if need_vo and vo_jobs:

        def _vo(job: tuple[int, str, Path]) -> tuple[int, str | None]:
            idx, line, dest = job
            try:
                return idx, str(generate_voiceover(line, dest, voice=voice))
            except Exception as exc:
                notes.append(f"VO fail: {exc}")
                return idx, None

        with ThreadPoolExecutor(max_workers=min(5, len(vo_jobs))) as pool:
            for fut in as_completed([pool.submit(_vo, j) for j in vo_jobs]):
                idx, path = fut.result()
                if path:
                    synced[idx]["audio"] = path
        if audio_mode == "voice":
            synced = [s for s in synced if s.get("audio")]
        if len(synced) < 3:
            return {"ok": False, "message": "VO failed for too many beats", "notes": notes}

    if credits:
        notes.append(pexels_mod.attribution_line(credits))

    out_path = root / "videos" / f"{_stem(topic, 'vid')}.mp4"
    try:
        video_path = build_fast_synced_beats(
            synced,
            out_path,
            fps=30,
            bitrate="16000k",
            out_size=(out_w, out_h),
            audio_mode=audio_mode,
        )
    except Exception as exc:
        return {"ok": False, "message": str(exc)[:240], "notes": notes, "beats": synced}

    elapsed = time.perf_counter() - t0
    notes.append(f"elapsed_sec={elapsed:.1f}")
    vo_script = " ".join(s.get("line") or "" for s in synced)

    return {
        "ok": True,
        "status": "ok",
        "action": "create_video",
        "topic": topic,
        "script": vo_script,
        "video_path": str(video_path),
        "beats": synced,
        "duration_sec": duration_sec,
        "aspect": "9:16" if vertical else "16:9",
        "audio_mode": audio_mode,
        "provider": "mira_jarvis_v8_director_pexels",
        "still_source": "pexels_video",
        "credits": credits,
        "elapsed_sec": round(elapsed, 1),
        "mira_engine": True,
        "is_trained_foundation_model": False,
        "director": plan.get("_director"),
        "plan_title": plan.get("title"),
        "message": (
            f"Video ready in {elapsed:.0f}s: {video_path.name} "
            f"(director · HD motion · {audio_mode})"
        ),
        "notes": notes,
        "learning_note": "Rate this with mira_rate to improve future quality.",
    }


def _run_video_stills_fallback(
    topic_clean: str,
    *,
    script: str | None,
    duration_sec: int,
    n_stills: int | None,
    aspect: str,
    style: str,
    voice: str | None,
    notes: list[str],
    prefer_ai: bool = False,
    audio_mode: str = "voice",
) -> dict[str, Any]:
    cfg = load_engine_config()
    still_cfg = cfg.get("still_gen") if isinstance(cfg.get("still_gen"), dict) else {}
    motion = cfg.get("motion") if isinstance(cfg.get("motion"), dict) else {}
    dur = max(12, min(90, int(duration_sec or 30)))
    count = int(n_stills or still_cfg.get("default_stills") or 5)
    count = max(3, min(6, count))
    if aspect in ("9:16", "vertical", "shorts"):
        width, height = 720, 1280
    else:
        width = int(still_cfg.get("width") or 1280)
        height = int(still_cfg.get("height") or 720)

    root = out_root()
    # prefer_ai → Pollinations first, then filtered Pexels fill (see generate_images)
    image_paths, credits, still_source = generate_images(
        topic_clean,
        count=count,
        width=width,
        height=height,
        style=style,
        upscale=bool(still_cfg.get("upscale", True)),
        prefer_pexels=not prefer_ai,
    )
    if not image_paths:
        return {
            "ok": False,
            "status": "error",
            "message": "No images generated — add PEXELS_API_KEY or retry Pollinations shortly.",
            "notes": notes,
        }
    if "pexels" in still_source:
        try:
            from jarvis.mira.pexels import attribution_line

            notes.append(attribution_line(credits))
        except Exception:
            notes.append("Photos provided by Pexels (https://www.pexels.com).")
    if "pollinations" in still_source:
        notes.append("Stills via Pollinations (free AI).")
    notes.append(f"still_source={still_source}")

    vo_script = (script or "").strip() or topic_clean
    mode = (audio_mode or "voice").strip().lower()
    audio_path: Optional[Path] = None
    if mode in ("voice", "both"):
        notes.append("vo=exact_brief_stills")
        try:
            audio_path = generate_voiceover(
                vo_script,
                root / "audio" / f"{_stem(topic_clean, 'vo')}.mp3",
                voice=voice,
            )
        except Exception as exc:
            notes.append(f"voiceover skipped: {exc}")
    else:
        notes.append(f"vo=skipped_{mode}")

    # Hard min ~3.5s per still — never ship a 1-second stub
    per = max(3.5, float(dur) / max(1, len(image_paths)))
    fps = int(cfg.get("fps") or 30)
    bitrate = str(cfg.get("bitrate") or "10000k")
    crossfade = float(motion.get("crossfade_sec") or 0.55)
    zoom = float(motion.get("zoom_span") or 0.18)
    video_path: Optional[Path] = None
    try:
        video_path = build_video(
            image_paths,
            audio_path,
            root / "videos" / f"{_stem(topic_clean, 'vid')}.mp4",
            duration_per_image=per,
            fps=fps,
            bitrate=bitrate,
            crossfade_sec=crossfade,
            zoom_span=zoom,
            out_size=(1080, 1920) if height > width else (1920, 1080),
        )
    except Exception as exc:
        notes.append(f"video failed: {exc}")
        return {
            "ok": False,
            "status": "error",
            "message": str(exc)[:240],
            "image_paths": [str(p) for p in image_paths],
            "notes": notes,
        }

    try:
        from jarvis.mira.fast_encode import _probe_duration

        got = float(_probe_duration(video_path) or 0)
        notes.append(f"stills_duration={got:.1f}")
        if got < max(8.0, dur * 0.4):
            notes.append("stills_duration_too_short_rebuilding")
            video_path = build_video(
                image_paths,
                None,
                root / "videos" / f"{_stem(topic_clean, 'vid')}.mp4",
                duration_per_image=max(4.0, float(dur) / max(1, len(image_paths))),
                fps=fps,
                bitrate=bitrate,
                crossfade_sec=0.0,
                zoom_span=0.0,
                out_size=(1080, 1920) if height > width else (1920, 1080),
            )
            got2 = float(_probe_duration(video_path) or 0)
            notes.append(f"stills_duration_rebuilt={got2:.1f}")
    except Exception as exc:
        notes.append(f"duration_guard:{exc}")

    return {
        "ok": True,
        "status": "ok",
        "action": "create_video",
        "topic": topic_clean,
        "script": vo_script,
        "image_paths": [str(p) for p in image_paths],
        "audio_path": str(audio_path) if audio_path else None,
        "video_path": str(video_path),
        "duration_sec": dur,
        "aspect": aspect,
        "audio_mode": mode,
        "provider": f"mira_jarvis_v2+{still_source}_stills_fallback",
        "still_source": still_source,
        "credits": credits,
        # Beats so verifier knows visuals+VO are the exact ask (not empty → fail)
        "beats": [
            {
                "kind": "still",
                "source": still_source or "still",
                "visual": str(p),
                "line": vo_script,
                "query": topic_clean,
                "heading": "STILL",
            }
            for p in image_paths
        ],
        "mira_engine": True,
        "is_trained_foundation_model": False,
        "message": f"Video ready (stills fallback): {video_path.name if video_path else 'unknown'}",
        "notes": notes,
        "learning_note": "Rate this with mira_rate to improve future quality.",
    }
