"""Screen record — save a desktop MP4 via ffmpeg gdigrab (Windows).

Chat:
  record my screen 20 seconds
  stop screen record
  screen recording status
"""

from __future__ import annotations

import re
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "screen_records"

_lock = threading.Lock()
_proc: subprocess.Popen[str] | None = None
_out_path: Path | None = None
_started_at: float = 0.0


def _ffmpeg() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def is_screen_record_intent(text: str) -> bool:
    t = (text or "").lower()
    return bool(
        re.search(
            r"\b("
            r"record(\s+my)?\s+screen|screen\s*record|"
            r"start\s+recording(\s+screen)?|"
            r"stop\s+(screen\s*)?record|"
            r"screen\s+recording\s+status|"
            r"recording\s+status"
            r")\b",
            t,
        )
    )


def _parse_seconds(text: str) -> int:
    m = re.search(r"(\d+)\s*(s|sec|secs|second|seconds)\b", text or "", re.I)
    if m:
        return max(3, min(600, int(m.group(1))))
    m = re.search(r"(\d+)\s*(m|min|mins|minute|minutes)\b", text or "", re.I)
    if m:
        return max(3, min(600, int(m.group(1)) * 60))
    return 15


def status() -> dict[str, Any]:
    with _lock:
        running = _proc is not None and _proc.poll() is None
        return {
            "running": running,
            "path": str(_out_path) if _out_path else None,
            "elapsed_sec": round(time.time() - _started_at, 1) if running and _started_at else 0,
        }


def stop_recording() -> str:
    global _proc, _out_path
    with _lock:
        proc = _proc
        path = _out_path
        _proc = None
    if not proc:
        return "No screen recording in progress, sir."
    try:
        proc.communicate(input="q", timeout=8)
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass
    time.sleep(0.4)
    if path and path.is_file() and path.stat().st_size > 1000:
        try:
            import os

            os.startfile(str(path))  # noqa: S606
        except Exception:
            pass
        return f"Screen recording saved: {path}"
    return "Recording stopped, but the file was empty or missing. Try again, sir."


def start_recording(seconds: int = 15) -> str:
    global _proc, _out_path, _started_at
    with _lock:
        if _proc is not None and _proc.poll() is None:
            return "Already recording, sir. Say 'stop screen record' first."
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        dest = OUT_DIR / f"rec_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.mp4"
        ff = _ffmpeg()
        # gdigrab desktop — Windows primary display
        cmd = [
            ff,
            "-y",
            "-f",
            "gdigrab",
            "-framerate",
            "15",
            "-i",
            "desktop",
            "-t",
            str(max(3, min(600, int(seconds)))),
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            str(dest),
        ]
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except Exception as exc:
            return f"Could not start screen record: {exc}"
        _proc = proc
        _out_path = dest
        _started_at = time.time()

    def _watch() -> None:
        global _proc
        try:
            proc.wait(timeout=max(5, int(seconds) + 30))
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        with _lock:
            if _proc is proc:
                _proc = None

    threading.Thread(target=_watch, daemon=True, name="screen-record").start()
    return (
        f"Recording screen for {int(seconds)}s → {dest.name}. "
        "Say 'stop screen record' early if needed."
    )


def run_screen_record(text: str) -> str:
    raw = (text or "").strip()
    lower = raw.lower()
    if re.search(r"\bstop\b", lower):
        return stop_recording()
    if re.search(r"\bstatus\b", lower):
        st = status()
        if st["running"]:
            return f"Recording… {st['elapsed_sec']}s so far → {st['path']}"
        return "No active screen recording, sir."
    secs = _parse_seconds(raw)
    return start_recording(secs)
