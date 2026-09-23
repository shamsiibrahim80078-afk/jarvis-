"""User credentials for autonomous sign-in — JARVIS_EMAIL / JARVIS_PASSWORD via identity."""

from __future__ import annotations

from jarvis.tools.command_parse import extract_email


def get_user_email(text: str = "") -> str | None:
    from jarvis import identity

    return extract_email(text) or identity.browser_email() or None


def get_user_password() -> str | None:
    from jarvis import identity

    pwd = identity.browser_password()
    return pwd if pwd else None


def mask_secret(value: str, show: int = 4) -> str:
    if len(value) <= show * 2:
        return "***"
    return value[:show] + "..." + value[-show:]
