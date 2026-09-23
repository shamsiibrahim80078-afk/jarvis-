"""System self-scan — detect issues and auto-fix what it can."""

from __future__ import annotations

import importlib
import os
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
REQUIRED = (
    "fastapi", "uvicorn", "openai", "requests", "psutil",
    "pyautogui", "edge_tts", "dotenv", "playwright",
)


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _check_import(pkg: str) -> bool:
    try:
        importlib.import_module(pkg.replace("-", "_") if pkg == "edge_tts" else pkg)
        return True
    except ImportError:
        return False


def _check_env() -> list[str]:
    issues = []
    env_path = ROOT / ".env"
    if not env_path.exists():
        issues.append("missing .env file")
        return issues
    content = env_path.read_text(encoding="utf-8")
    if "GROQ_API_KEY=" in content and not _has_value(content, "GROQ_API_KEY"):
        issues.append("GROQ_API_KEY empty")
    if "JARVIS_EMAIL=" not in content:
        issues.append("JARVIS_EMAIL not set (needed for auto sign-in)")
    return issues


def _has_value(content: str, key: str) -> bool:
    for line in content.splitlines():
        if line.startswith(f"{key}="):
            return bool(line.split("=", 1)[1].strip())
    return False


def _fix_missing_packages(missing: list[str]) -> list[str]:
    fixed = []
    if not missing:
        return fixed
    pip = str(ROOT / ".venv" / "Scripts" / "pip.exe")
    if not Path(pip).exists():
        pip = "pip"
    try:
        subprocess.run(
            [pip, "install", *missing, "-q"],
            cwd=str(ROOT),
            capture_output=True,
            timeout=120,
            check=False,
        )
        fixed.append(f"installed: {', '.join(missing)}")
    except Exception as exc:
        fixed.append(f"install failed: {exc}")
    return fixed


def scan_and_fix(text: str = "") -> str:
    """Scan Jarvis system, auto-fix issues, report status."""
    lower = text.lower()
    auto_fix = "fix" in lower or "repair" in lower or "solve" in lower or not text

    issues: list[str] = []
    fixes: list[str] = []

    # Python packages
    missing = [p for p in REQUIRED if not _check_import(p)]
    if missing:
        issues.append(f"missing packages: {', '.join(missing)}")
        if auto_fix:
            fixes.extend(_fix_missing_packages(missing))

    # .env
    env_issues = _check_env()
    issues.extend(env_issues)

    # Server port
    if not _port_in_use(8765):
        issues.append("Jarvis server not running on port 8765")
        if auto_fix:
            fixes.append("start server with: python run_server.py")

    # Playwright browsers
    if _check_import("playwright") and auto_fix:
        try:
            result = subprocess.run(
                [str(VENV_PYTHON), "-m", "playwright", "install", "chrome"],
                capture_output=True,
                timeout=180,
                cwd=str(ROOT),
            )
            if result.returncode == 0:
                fixes.append("playwright chrome ready")
        except Exception:
            issues.append("playwright chrome not installed")

    # Core imports
    try:
        from jarvis.fast_router import try_fast_command  # noqa: F401
        from jarvis.tools.api_hunter import fetch_api_key  # noqa: F401
        from jarvis.tools.api_pipeline import run_batch_from_sheet  # noqa: F401
    except Exception as exc:
        issues.append(f"code import error: {exc}")

    # Data dirs
    for d in ("data", "data/apis", "data/screenshots", "config"):
        p = ROOT / d
        if not p.exists() and auto_fix:
            p.mkdir(parents=True, exist_ok=True)
            fixes.append(f"created {d}/")

    lines = ["System scan complete, sir."]
    if issues:
        lines.append("Issues found:")
        for i in issues:
            lines.append(f"  - {i}")
    else:
        lines.append("All systems operational.")

    if fixes:
        lines.append("Auto-fixed:")
        for f in fixes:
            lines.append(f"  + {f}")

    if env_issues and "JARVIS_EMAIL" in str(env_issues):
        lines.append("Tip: Add JARVIS_EMAIL and JARVIS_PASSWORD to .env for full auto sign-in.")

    return "\n".join(lines)


def is_scan_command(text: str) -> bool:
    lower = text.lower()
    return any(w in lower for w in (
        "scan system", "scan your system", "check system", "any bug",
        "find bug", "fix bug", "self repair", "diagnose", "health check",
        "system scan", "scan for bug",
    ))
