"""Voice input/output - Edge TTS, Fish Audio, wake word support."""

from __future__ import annotations

import asyncio
import os
import tempfile
from typing import Callable

import edge_tts
import requests
import speech_recognition as sr

try:
    import pygame
    pygame.mixer.init()
    HAS_PYGAME = True
except Exception:
    HAS_PYGAME = False


class Voice:
    def __init__(
        self,
        voice_id: str = "en-GB-RyanNeural",
        listen_timeout: int = 10,
        phrase_limit: int = 20,
        tts_engine: str = "edge",
        on_status: Callable[[str], None] | None = None,
    ) -> None:
        self.voice_id = voice_id
        self.listen_timeout = listen_timeout
        self.phrase_limit = phrase_limit
        self.tts_engine = os.getenv("JARVIS_TTS_ENGINE", tts_engine).lower()
        self._fish_key = os.getenv("FISH_AUDIO_API_KEY", "")
        if self._fish_key and self.tts_engine == "auto":
            self.tts_engine = "fish"
        self.on_status = on_status
        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold = 300
        self.recognizer.dynamic_energy_threshold = True
        self._mic: sr.Microphone | None = None

    def _status(self, s: str) -> None:
        if self.on_status:
            self.on_status(s)

    def _get_mic(self) -> sr.Microphone:
        if self._mic is None:
            self._mic = sr.Microphone()
        return self._mic

    def calibrate(self) -> None:
        with self._get_mic() as source:
            self._status("CALIBRATING")
            self.recognizer.adjust_for_ambient_noise(source, duration=1)
            self._status("ONLINE")

    def listen(self, wait_for_wake: bool = False, wake_word: str = "jarvis") -> str | None:
        with self._get_mic() as source:
            self._status("LISTENING")
            try:
                audio = self.recognizer.listen(
                    source,
                    timeout=self.listen_timeout,
                    phrase_time_limit=self.phrase_limit,
                )
            except sr.WaitTimeoutError:
                self._status("ONLINE")
                return None

        try:
            text = self.recognizer.recognize_google(audio)
            self._status("ONLINE")
            if wait_for_wake and wake_word not in text.lower():
                return None
            if wake_word in text.lower():
                text = text.lower().replace(wake_word, "").strip(" ,.!")
            return text or None
        except sr.UnknownValueError:
            self._status("ONLINE")
            return None
        except sr.RequestError as exc:
            self._status("ONLINE")
            print(f"Speech error: {exc}")
            return None

    async def _edge_tts(self, text: str, path: str) -> None:
        await edge_tts.Communicate(text, self.voice_id).save(path)

    def _fish_tts(self, text: str, path: str) -> None:
        r = requests.post(
            "https://api.fish.audio/v1/tts",
            headers={
                "Authorization": f"Bearer {self._fish_key}",
                "model": "s2.1-pro-free",
                "Content-Type": "application/json",
            },
            json={"text": text},
            timeout=30,
        )
        r.raise_for_status()
        with open(path, "wb") as f:
            f.write(r.content)

    def speak(self, text: str) -> None:
        if not text.strip():
            return
        print(f"Jarvis: {text}")
        self._status("SPEAKING")

        if not HAS_PYGAME:
            self._status("ONLINE")
            return

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            if self.tts_engine == "fish" and self._fish_key:
                self._fish_tts(text, tmp_path)
            else:
                asyncio.run(self._edge_tts(text, tmp_path))
            pygame.mixer.music.load(tmp_path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                pygame.time.Clock().tick(10)
        except Exception as exc:
            print(f"TTS fallback: {exc}")
            if self.tts_engine == "fish":
                asyncio.run(self._edge_tts(text, tmp_path))
                pygame.mixer.music.load(tmp_path)
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():
                    pygame.time.Clock().tick(10)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        self._status("ONLINE")
