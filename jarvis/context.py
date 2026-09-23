"""Session context — remembers what user was doing (YouTube, sheet, etc.)."""

from __future__ import annotations

_context: dict[str, str | None] = {
    "mode": None,       # youtube | sheet | none
    "sheet_url": None,
    "last_query": None,
    "last_provider": None,
    "last_site": None,
}


def set_context(mode: str | None, **extra: str | None) -> None:
    if mode:
        _context["mode"] = mode
    for k, v in extra.items():
        if v is not None:
            _context[k] = v


def get_context() -> dict[str, str | None]:
    return dict(_context)


def clear_context() -> None:
    _context["mode"] = None
    _context["sheet_url"] = None
    _context["last_query"] = None
    _context["last_provider"] = None
    _context["last_site"] = None
