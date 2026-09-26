"""Screen record — save a desktop MP4 via ffmpeg gdigrab (Windows).

Chat:
  record my screen 20 seconds
  stop screen record
  screen recording status
  open my latest screen recording
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "screen_records"

# Short grace only — enough to catch immediate encoder/gdigrab failures
_STARTUP_GRACE_SEC = 0.45
# Same floor as stop_recording / failed-start cleanup — skip empty leftovers
_MIN_VALID_BYTES = 1000

_lock = threading.Lock()
_proc: subprocess.Popen[str] | None = None
_out_path: Path | None = None
_started_at: float = 0.0

_OPEN_LATEST_RE = re.compile(
    r"\b("
    r"(?:open|show)\s+(?:my\s+)?(?:latest|last)\s+screen\s*record(?:ing)?"
    r"|open\s+(?:my\s+)?(?:latest|last)\s+recording"
    r")\b",
    re.I,
)


def _ffmpeg() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def is_open_latest_intent(text: str) -> bool:
    return bool(_OPEN_LATEST_RE.search(text or ""))


def is_screen_record_intent(text: str) -> bool:
    t = (text or "").lower()
    if is_open_latest_intent(t):
        return True
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


def get_latest_recording() -> Path | None:
    """Newest valid MP4 under data/screen_records (disk, survives restarts)."""
    if not OUT_DIR.is_dir():
        return None
    best: Path | None = None
    best_mtime = -1.0
    try:
        candidates = OUT_DIR.glob("*.mp4")
    except Exception:
        return None
    for p in candidates:
        try:
            st = p.stat()
        except OSError:
            continue
        if st.st_size < _MIN_VALID_BYTES:
            continue
        if st.st_mtime >= best_mtime:
            best_mtime = st.st_mtime
            best = p
    return best.resolve() if best is not None else None


def _open_local_mp4(path: Path) -> None:
    os.startfile(str(path))  # noqa: S606


def open_latest_recording() -> str:
    """Open newest valid screen recording from disk (not Chrome)."""
    path = get_latest_recording()
    if path is None:
        return "No screen recording is available yet."
    try:
        _open_local_mp4(path)
    except Exception as exc:
        return f"Found recording {path.name} but could not open it: {exc}"
    return f"Opening latest screen recording: {path}"


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
    if path and path.is_file() and path.stat().st_size >= _MIN_VALID_BYTES:
        try:
            _open_local_mp4(path)
        except Exception:
            pass
        return f"Screen recording saved: {path}"
    return "Recording stopped, but the file was empty or missing. Try again, sir."


def _read_err_tail(err_path: Path, limit: int = 700) -> str:
    try:
        if not err_path.is_file():
            return ""
        text = err_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    text = text.strip()
    if not text:
        return ""
    # Prefer the most useful encoder/gdigrab line
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for ln in reversed(lines):
        low = ln.lower()
        if any(
            k in low
            for k in (
                "error",
                "invalid",
                "not divisible",
                "failed",
                "could not",
                "conversion failed",
                "unknown",
            )
        ):
            return ln[:240]
    return (lines[-1] if lines else text)[:240]


def _cleanup_failed_start(dest: Path, err_path: Path) -> None:
    """Remove only this attempt's empty/invalid output + err log. Never touch older recs."""
    try:
        if dest.is_file() and dest.stat().st_size < _MIN_VALID_BYTES:
            dest.unlink(missing_ok=True)
    except Exception:
        pass
    try:
        err_path.unlink(missing_ok=True)
    except Exception:
        pass


def start_recording(seconds: int = 15) -> str:
    global _proc, _out_path, _started_at
    try:
        from jarvis.tools.resource_guard import can_start_heavy_job, soft_reclaim

        ok, reason, _snap = can_start_heavy_job(kind="screen_record")
        if not ok:
            return reason
        soft_reclaim()
    except Exception:
        pass

    with _lock:
        if _proc is not None and _proc.poll() is None:
            return "Already recording, sir. Say 'stop screen record' first."

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dest = OUT_DIR / f"rec_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.mp4"
    err_path = dest.with_suffix(".ffmpeg.err")
    ff = _ffmpeg()
    # gdigrab desktop — low-resource defaults for ~4 GB machines
    # 10 fps + half scale + CRF 28 keeps peak encode RAM/CPU down
    cmd = [
        ff,
        "-y",
        "-f",
        "gdigrab",
        "-framerate",
        "10",
        "-i",
        "desktop",
        "-t",
        str(max(3, min(600, int(seconds)))),
        "-vf",
        # Half-res for ~4GB RAM; force even dims (libx264 rejects odd widths
        # e.g. 1366x768 → iw/2=683). trunc(x/2)*2 keeps ~half scale.
        "scale=trunc(iw/2/2)*2:trunc(ih/2/2)*2",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "28",
        "-pix_fmt",
        "yuv420p",
        "-threads",
        "1",
        str(dest),
    ]

    try:
        err_f = open(err_path, "w", encoding="utf-8", errors="replace")
    except Exception as exc:
        return f"Could not start screen record: {exc}"

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=err_f,
            text=True,
        )
    except Exception as exc:
        try:
            err_f.close()
        except Exception:
            pass
        _cleanup_failed_start(dest, err_path)
        return f"Could not start screen record: {exc}"

    # Lightweight startup validation — do not claim running until process survives
    deadline = time.time() + _STARTUP_GRACE_SEC
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        time.sleep(0.05)

    if proc.poll() is not None:
        try:
            err_f.flush()
            err_f.close()
        except Exception:
            pass
        # Reap zombie
        try:
            proc.wait(timeout=1)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        err_line = _read_err_tail(err_path) or f"ffmpeg exited immediately (code {proc.returncode})"
        _cleanup_failed_start(dest, err_path)
        with _lock:
            if _proc is proc:
                _proc = None
        return f"Screen record failed to start: {err_line}"

    # Survived grace — now mark active
    with _lock:
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
        finally:
            try:
                err_f.close()
            except Exception:
                pass
            try:
                err_path.unlink(missing_ok=True)
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
    if is_open_latest_intent(lower):
        return open_latest_recording()
    if re.search(r"\bstop\b", lower):
        return stop_recording()
    if re.search(r"\bstatus\b", lower):
        st = status()
        if st["running"]:
            return f"Recording… {st['elapsed_sec']}s so far → {st['path']}"
        return "No active screen recording, sir."
    secs = _parse_seconds(raw)
    return start_recording(secs)
