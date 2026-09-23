"""Run API hunt in isolated process (Playwright needs this on Windows).

Includes auto-retry: if the first attempt fails, retries once after 5s.
"""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LOG = ROOT / "data" / "hunt_worker.log"
MAX_RETRIES = 2

_SECRET_RE = re.compile(
    r"(?:gsk_[A-Za-z0-9]+|sk-ant-[A-Za-z0-9_-]+|sk-or-[A-Za-z0-9_-]+|"
    r"sk_[a-f0-9]+|sk-[A-Za-z0-9_-]+|AIza[A-Za-z0-9_-]+|"
    r"nvapi-[A-Za-z0-9_-]+|hf_[A-Za-z0-9]+)"
)


def _mask_secrets(text: str) -> str:
    def _repl(m: re.Match[str]) -> str:
        s = m.group(0)
        if len(s) <= 10:
            return "***"
        return s[:4] + "..." + s[-4:]

    return _SECRET_RE.sub(_repl, text)


def _log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{time.strftime('%H:%M:%S')}] {_mask_secrets(msg)}\n")


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: hunt_worker.py <command text>")

    text = sys.argv[1]
    LOG.parent.mkdir(parents=True, exist_ok=True)

    lock = ROOT / "data" / "hunt.lock"
    try:
        if lock.exists():
            age = time.time() - lock.stat().st_mtime
            stale = age >= 600
            # Stale if lock owner PID is dead
            try:
                raw = lock.read_text(encoding="utf-8").strip()
                owner_pid = int((raw.split("|", 1)[0] or "0").strip() or "0")
            except Exception:
                owner_pid = 0
            if owner_pid > 0:
                try:
                    import os

                    os.kill(owner_pid, 0)
                    alive = True
                except OSError:
                    alive = False
                except Exception:
                    alive = age < 600
                if not alive:
                    stale = True
            if not stale and age < 600:
                _log("Another hunt is already running — aborting duplicate")
                from jarvis.tools.hunt_bus import set_failed

                set_failed(text, "Hunt already running, sir — wait for the current Chrome hunt to finish.")
                return
            try:
                lock.unlink(missing_ok=True)
            except Exception:
                pass
        lock.write_text(f"{os.getpid()}|{time.time()}", encoding="utf-8")
    except Exception:
        pass

    from jarvis.tools.api_hunter import _fetch_blocking
    from jarvis.tools.hunt_bus import set_done, set_failed

    last_error = ""
    try:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                _log(f"ATTEMPT {attempt}/{MAX_RETRIES}: {text}")
                result = _fetch_blocking(text)

                # Check if the result indicates success (contains a key)
                if result and ("API key" in result or "sk-" in result or "gsk_" in result
                               or "sk_" in result or "hf_" in result or "AIza" in result
                               or "nvapi-" in result or "already have" in result.lower()
                               or "Saved your" in result or "Saved to .env" in result):
                    set_done(text, result)  # full key goes to UI via hunt_bus
                    _log(f"DONE: {_mask_secrets(result[:500])}")
                    return

                fail_hints = (
                    "stuck on the email",
                    "complete sign-in in chrome",
                    "password field never",
                    "could not find the email",
                    "could not find the password",
                    "google sign-in did not finish",
                    "hunt already running",
                )
                low = (result or "").lower()
                if result and any(h in low for h in fail_hints) and "got your" not in low:
                    set_failed(text, result)
                    _log(f"FAIL: {_mask_secrets(result[:500])}")
                    return

                # Result is a "Chrome is still open" / manual message — still set done
                set_done(text, result)
                _log(f"DONE (manual): {_mask_secrets(result[:500])}")
                return

            except Exception as exc:
                last_error = str(exc)
                _log(f"ERROR attempt {attempt}: {exc}")
                if attempt < MAX_RETRIES:
                    _log("Retrying in 5s...")
                    time.sleep(5)

        set_failed(text, f"Failed after {MAX_RETRIES} attempts: {last_error}")
        _log(f"FINAL FAIL: {last_error}")
    finally:
        try:
            lock.unlink(missing_ok=True)
        except Exception:
            pass


if __name__ == "__main__":
    main()
