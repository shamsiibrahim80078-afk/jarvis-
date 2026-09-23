"""Local API key registry — mirrors your sheet; .env writes are opt-in only."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "data" / "api_registry.json"
ENV_PATH = ROOT / ".env"


def _load() -> dict:
    if not REGISTRY_PATH.exists():
        return {"providers": {}, "sheet_url": ""}
    try:
        return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"providers": {}, "sheet_url": ""}


def _save(data: dict) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def save_key(
    provider: str,
    key: str,
    env_var: str = "",
    sheet_row: str = "",
    *,
    write_env: bool = False,
) -> None:
    """Store key in local registry. Writes .env only when write_env=True."""
    data = _load()
    data["providers"][provider.lower()] = {
        "key": key,
        "env_var": env_var,
        "sheet_row": sheet_row,
        "status": "ok",
        "updated": datetime.now(timezone.utc).isoformat(),
    }
    _save(data)
    if write_env and env_var:
        _write_env(env_var, key)


def write_key_to_env(provider: str, key: str = "", env_var: str = "") -> str | None:
    """Write a provider key to .env. Returns env var name written, or None."""
    pid = provider.lower()
    data = _load()
    entry = data.get("providers", {}).get(pid, {})
    value = key or (entry.get("key") or "")
    if not value:
        # Fall back to get_key (registry + existing .env)
        value = get_key(pid) or ""
    if not value:
        return None

    env_name = env_var or entry.get("env_var") or ""
    if not env_name:
        try:
            from jarvis.tools.api_hunter import PROVIDERS
            env_name = PROVIDERS.get(pid, {}).get("env_key", "")
        except Exception:
            env_name = ""
    if not env_name:
        env_name = f"{pid.upper()}_API_KEY"

    # Keep registry in sync
    save_key(pid, value, env_name, write_env=True)
    return env_name


def get_key(provider: str) -> str | None:
    import os
    from dotenv import load_dotenv

    data = _load()
    entry = data.get("providers", {}).get(provider.lower())
    if entry and entry.get("key"):
        return entry["key"]

    # Also check .env for known providers
    try:
        from jarvis.tools.api_hunter import PROVIDERS
        cfg = PROVIDERS.get(provider.lower())
        if cfg:
            load_dotenv(ENV_PATH, override=True)
            val = os.getenv(cfg.get("env_key", ""), "").strip()
            if val:
                return val
    except Exception:
        pass
    return None


def list_all() -> dict:
    return _load().get("providers", {})


def set_sheet_url(url: str) -> None:
    data = _load()
    data["sheet_url"] = url
    _save(data)


def _write_env(env_key: str, value: str) -> None:
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    out: list[str] = []
    found = False
    for line in lines:
        if line.startswith(f"{env_key}="):
            out.append(f"{env_key}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{env_key}={value}")
    ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")


def export_summary() -> str:
    providers = list_all()
    if not providers:
        return "No API keys in registry yet, sir."
    lines = ["API Registry:"]
    for name, info in providers.items():
        key = info.get("key", "")
        preview = key[:8] + "..." if len(key) > 12 else key
        lines.append(f"  {name}: {preview} ({info.get('status', '?')})")
    return "\n".join(lines)
