"""Prompt engineer plugin — Cursor brief + email result."""

from __future__ import annotations

from jarvis.tools.prompt_engineer import handle as _handle


def handle(text: str) -> str | None:
    return _handle(text)
