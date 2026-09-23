"""API key hunter plugin — sign in and fetch API keys."""

from jarvis.tools.api_hunter import fetch_api_key
from jarvis.tools.command_parse import is_api_key_command


def handle(text: str) -> str | None:
    if not is_api_key_command(text):
        return None
    return fetch_api_key(text)
