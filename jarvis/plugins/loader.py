"""Plugin loader - drop .py files in plugins/ folder."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
PLUGINS_DIR = ROOT / "plugins"


def load_plugins() -> dict[str, ModuleType]:
    plugins: dict[str, ModuleType] = {}
    PLUGINS_DIR.mkdir(parents=True, exist_ok=True)

    for file in PLUGINS_DIR.glob("*.py"):
        if file.name.startswith("_"):
            continue
        name = file.stem
        spec = importlib.util.spec_from_file_location(f"plugins.{name}", file)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"plugins.{name}"] = module
        try:
            spec.loader.exec_module(module)
            plugins[name] = module
        except Exception:
            continue
    return plugins


def run_plugin_command(plugins: dict[str, ModuleType], text: str) -> str | None:
    """Let plugins handle a command. Return response or None."""
    for module in plugins.values():
        handler = getattr(module, "handle", None)
        if callable(handler):
            try:
                result = handler(text)
                if result:
                    return str(result)
            except Exception:
                continue
    return None
