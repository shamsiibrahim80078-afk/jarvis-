"""TTS — Edge British (fast) + Fish Audio (quality)."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

import edge_tts
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

logger = logging.getLogger("jarvis.tts")

# British butler voice — sounds like Jarvis
EDGE_VOICE = os.getenv("JARVIS_VOICE", "en-GB-RyanNeural")
# Fish Audio voice ID (British male style)
FISH_VOICE_ID = os.getenv("FISH_VOICE_ID", "9a9cf47702da476aa4629e2506d4a857")


def _fish_tts(text: str) -> bytes | None:
    key = os.getenv("FISH_AUDIO_API_KEY", "").strip()
    if not key:
        return None
    try:
        payload: dict = {
            "text": text,
            "format": "mp3",
            "latency": "balanced",
        }
        if FISH_VOICE_ID:
            payload["reference_id"] = FISH_VOICE_ID

        r = requests.post(
            "https://api.fish.audio/v1/tts",
            headers={
                "Authorization": f"Bearer {key}",
                "model": "s2.1-pro-free",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=20,
        )
        if r.status_code == 200 and len(r.content) > 100:
            return r.content
        logger.warning("Fish TTS: %s %s", r.status_code, r.text[:150])
    except Exception as exc:
        logger.warning("Fish TTS error: %s", exc)
    return None


async def _edge_tts(text: str) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        path = tmp.name
    try:
        await edge_tts.Communicate(text, EDGE_VOICE).save(path)
        return Path(path).read_bytes()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


async def generate_tts_audio(text: str, fast: bool = True) -> tuple[bytes, str]:
    """fast=True uses Edge TTS first (sub-second British Jarvis voice)."""
    text = text.strip()
    if not text:
        return b"", "audio/mpeg"

    engine = os.getenv("JARVIS_TTS_ENGINE", "edge").lower()

    # Edge first = flash fast British Jarvis
    if engine in ("edge", "auto") or fast:
        try:
            audio = await _edge_tts(text)
            if audio:
                return audio, "audio/mpeg"
        except Exception as exc:
            logger.warning("Edge TTS: %s", exc)

    if engine in ("fish", "auto"):
        audio = _fish_tts(text)
        if audio:
            return audio, "audio/mpeg"

    return b"", "audio/mpeg"
