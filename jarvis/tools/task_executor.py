"""Multi-step task executor — one command, multiple actions."""

from __future__ import annotations

import re

from jarvis.fast_router import try_fast_command
from jarvis.tools import system
from jarvis.tools.command_parse import (
    extract_sheet_tab_name,
    extract_urls,
    is_file_transfer_command,
    is_link_command,
    is_sheet_context_command,
    is_sheet_command,
    normalize,
    split_task_steps,
)
from jarvis.tools.files_tool import copy_files, list_folder, parse_transfer_command
from jarvis.tools.sheets import check_apis, navigate_sheet_tab, open_google_sheet, sync_apis_to_env
from jarvis.tools.api_pipeline import count_apis_from_sheet, is_api_count_command
from jarvis.tools.workflows import get_link, set_link, set_folder, set_sheet_tab


def try_task_command(text: str) -> str | None:
    """Run compound or advanced tasks. Returns None if not handled."""
    raw = text.strip()
    if not raw:
        return None

    # Remember saved links/folders
    remember = _try_remember(raw)
    if remember:
        return remember

    # Sheet API counts — never fall through
    if is_api_count_command(raw):
        return count_apis_from_sheet(raw)

    # Direct URL open
    if is_link_command(raw):
        urls = extract_urls(raw)
        if urls:
            return system.open_in_chrome(urls[0])

    # File transfer
    if is_file_transfer_command(raw):
        transfer = parse_transfer_command(raw)
        if transfer:
            return copy_files(transfer[0], transfer[1])

    # Multi-step compound command
    steps = split_task_steps(raw)
    if len(steps) > 1:
        return _run_steps(steps, raw)

    # Single advanced tasks
    return _run_single_advanced(raw)


def _try_remember(text: str) -> str | None:
    lower = normalize(text)
    urls = extract_urls(text)

    m = re.search(r"remember\s+(?:my\s+)?(?:the\s+)?(.+?)\s+(?:is|as)\s+(.+)", lower)
    if m and urls:
        name = m.group(1).strip()
        return set_link(name, urls[0])

    if "remember" in lower and urls:
        name = "api_sheet" if "sheet" in lower else "saved_link"
        return set_link(name, urls[0])

    m = re.search(r"remember\s+tab\s+(.+?)\s+(?:gid\s+)?(?:is\s+)?(\d+)", lower)
    if m:
        return set_sheet_tab(m.group(1).strip(), m.group(2))

    m = re.search(r"remember\s+(?:folder\s+)?(.+?)\s+(?:is|as)\s+(.+)", lower)
    if m and ":\\" in text:
        from jarvis.tools.command_parse import extract_windows_paths
        paths = extract_windows_paths(text)
        if paths:
            return set_folder(m.group(1).strip(), paths[0])

    return None


def _run_single_advanced(text: str) -> str | None:
    lower = normalize(text)
    urls = extract_urls(text)

    tab = extract_sheet_tab_name(text)
    if tab:
        return navigate_sheet_tab(tab, urls[0] if urls else get_link("api_sheet"))

    if is_sheet_context_command(text):
        tab = extract_sheet_tab_name(text)
        if tab:
            return navigate_sheet_tab(tab)
        return open_google_sheet(urls[0] if urls else None)

    if is_sheet_command(text) or "api sheet" in lower:
        sheet_url = urls[0] if urls else get_link("api_sheet")
        if "check" in lower and "api" in lower:
            return check_apis(sheet_url)
        if "sync" in lower or "upload" in lower and "env" in lower:
            return sync_apis_to_env(sheet_url)
        return open_google_sheet(sheet_url)

    if "check" in lower and "api" in lower:
        return check_apis(urls[0] if urls else None)

    if "list" in lower and ("folder" in lower or "files" in lower or "directory" in lower):
        from jarvis.tools.command_parse import extract_windows_paths
        paths = extract_windows_paths(text)
        if paths:
            return list_folder(paths[0])
        return list_folder("apis")

    return None


def _run_steps(steps: list[str], full_text: str) -> str | None:
    results: list[str] = []
    sheet_url = extract_urls(full_text)
    sheet_url = sheet_url[0] if sheet_url else get_link("api_sheet")

    for step in steps:
        r = (
            try_fast_command(step)
            or _run_single_advanced(step)
            or _run_step_keyword(step, sheet_url)
        )
        if r:
            results.append(r)

    if results:
        return " ".join(results)
    return None


def _run_step_keyword(step: str, sheet_url: str | None) -> str | None:
    lower = normalize(step)

    if "google sheet" in lower or "spreadsheet" in lower or "open sheet" in lower:
        return open_google_sheet(sheet_url)

    if "check" in lower and "api" in lower:
        return check_apis(sheet_url)

    if ("sync" in lower or "upload" in lower) and "api" in lower:
        return sync_apis_to_env(sheet_url)

    if "open" in lower:
        urls = extract_urls(step)
        if urls:
            return system.open_in_chrome(urls[0])
        fast = try_fast_command(step)
        if fast:
            return fast

    return try_fast_command(step)
