"""Screen-record startup honesty — fail fast if ffmpeg dies immediately."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import jarvis.tools.screen_record as sr


class _DeadProc:
    def __init__(self, code: int = 1) -> None:
        self.returncode = code

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        return None

    def communicate(self, input=None, timeout=None):
        return ("", "")


class _AliveProc:
    def __init__(self) -> None:
        self.returncode = None
        self._killed = False

    def poll(self):
        return None if not self._killed else 1

    def wait(self, timeout=None):
        import time

        time.sleep(0.05)
        return 0

    def kill(self):
        self._killed = True
        self.returncode = 1

    def communicate(self, input=None, timeout=None):
        self._killed = True
        return ("", "")


def test_startup_failure_no_fake_running(tmp_path, monkeypatch):
    monkeypatch.setattr(sr, "OUT_DIR", tmp_path)
    monkeypatch.setattr(sr, "_STARTUP_GRACE_SEC", 0.15)
    monkeypatch.setattr(sr, "_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(
        "jarvis.tools.resource_guard.can_start_heavy_job",
        lambda **k: (True, "", {}),
    )
    monkeypatch.setattr("jarvis.tools.resource_guard.soft_reclaim", lambda: {})

    dest_holder: dict = {}

    def fake_popen(cmd, **kwargs):
        # Create empty dest like ffmpeg would
        dest = Path(cmd[-1])
        dest_holder["dest"] = dest
        dest.write_bytes(b"")
        err = kwargs.get("stderr")
        if err and hasattr(err, "write"):
            err.write(
                "[libx264] width not divisible by 2 (683x384)\nConversion failed!\n"
            )
            err.flush()
        return _DeadProc(1)

    monkeypatch.setattr(sr.subprocess, "Popen", fake_popen)

    # Reset module globals
    with sr._lock:
        sr._proc = None
        sr._out_path = None
        sr._started_at = 0.0

    msg = sr.start_recording(5)
    assert "failed to start" in msg.lower()
    assert "not divisible" in msg.lower() or "conversion failed" in msg.lower() or "exited" in msg.lower()
    st = sr.status()
    assert st["running"] is False
    assert sr._proc is None
    # Invalid empty file cleaned
    dest = dest_holder.get("dest")
    assert dest is not None
    assert not dest.is_file()


def test_startup_success_marks_running(tmp_path, monkeypatch):
    monkeypatch.setattr(sr, "OUT_DIR", tmp_path)
    monkeypatch.setattr(sr, "_STARTUP_GRACE_SEC", 0.1)
    monkeypatch.setattr(sr, "_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(
        "jarvis.tools.resource_guard.can_start_heavy_job",
        lambda **k: (True, "", {}),
    )
    monkeypatch.setattr("jarvis.tools.resource_guard.soft_reclaim", lambda: {})

    alive = _AliveProc()

    def fake_popen(cmd, **kwargs):
        return alive

    monkeypatch.setattr(sr.subprocess, "Popen", fake_popen)

    with sr._lock:
        sr._proc = None
        sr._out_path = None
        sr._started_at = 0.0

    msg = sr.start_recording(5)
    assert "recording screen" in msg.lower()
    assert "failed" not in msg.lower()
    st = sr.status()
    assert st["running"] is True
    assert sr._proc is alive

    # Cleanup: stop without opening file
    with sr._lock:
        sr._proc = None
    alive.kill()
