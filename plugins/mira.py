"""Mira creative pipeline — generate AI images/videos (any topic)."""

from jarvis.tools.mira_tool import try_mira_command


def handle(text: str) -> str | None:
    # Sync for plugin path; HUD uses /api/mira background jobs instead.
    return try_mira_command(text, background=False)
