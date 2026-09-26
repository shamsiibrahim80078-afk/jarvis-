"""Persistent latest screen-recording discovery + open command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import jarvis.tools.screen_record as sr
from jarvis.fast_router import try_fast_command


def test_get_latest_empty_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(sr, "OUT_DIR", tmp_path)
    assert sr.get_latest_recording() is None
    assert sr.open_latest_recording() == "No screen recording is available yet."


def test_get_latest_ignores_zero_byte(tmp_path, monkeypatch):
    monkeypatch.setattr(sr, "OUT_DIR", tmp_path)
    older = tmp_path / "rec_old.mp4"
    older.write_bytes(b"x" * 2000)
    # newer but invalid
    newer = tmp_path / "rec_new_empty.mp4"
    newer.write_bytes(b"")
    # ensure mtime order: empty is newer
    import os
    import time

    older_m = time.time() - 10
    newer_m = time.time()
    os.utime(older, (older_m, older_m))
    os.utime(newer, (newer_m, newer_m))

    got = sr.get_latest_recording()
    assert got is not None
    assert got.resolve() == older.resolve()


def test_get_latest_persists_without_in_memory(tmp_path, monkeypatch):
    monkeypatch.setattr(sr, "OUT_DIR", tmp_path)
    f = tmp_path / "rec_persist.mp4"
    f.write_bytes(b"y" * 2500)
    with sr._lock:
        sr._proc = None
        sr._out_path = None
        sr._started_at = 0.0
    got = sr.get_latest_recording()
    assert got is not None
    assert got.resolve() == f.resolve()
    assert sr.status()["path"] is None  # not from in-memory


def test_open_latest_uses_startfile_not_chrome(tmp_path, monkeypatch):
    monkeypatch.setattr(sr, "OUT_DIR", tmp_path)
    f = tmp_path / "rec_open.mp4"
    f.write_bytes(b"z" * 1500)
    opened: list[str] = []
    monkeypatch.setattr(sr, "_open_local_mp4", lambda p: opened.append(str(p)))
    chrome = MagicMock(return_value="Opening in Chrome, sir.")
    monkeypatch.setattr("jarvis.tools.system.open_in_chrome", chrome)

    phrases = [
        "open my latest screen recording",
        "open latest screen recording",
        "show my latest screen recording",
        "open my last screen recording",
    ]
    for phrase in phrases:
        assert sr.is_open_latest_intent(phrase)
        assert sr.is_screen_record_intent(phrase)
        msg = try_fast_command(phrase)
        assert msg is not None
        assert "Opening latest screen recording" in msg
        assert f.name in msg
        assert "Chrome" not in msg
    assert len(opened) == len(phrases)
    chrome.assert_not_called()


def test_open_latest_does_not_start_ffmpeg(tmp_path, monkeypatch):
    monkeypatch.setattr(sr, "OUT_DIR", tmp_path)
    f = tmp_path / "rec_no_ffmpeg.mp4"
    f.write_bytes(b"a" * 1500)
    monkeypatch.setattr(sr, "_open_local_mp4", lambda p: None)
    popen = MagicMock()
    monkeypatch.setattr(sr.subprocess, "Popen", popen)
    with sr._lock:
        sr._proc = None
        sr._out_path = None
    msg = sr.run_screen_record("open my latest screen recording")
    assert "Opening latest" in msg
    popen.assert_not_called()
    assert sr.status()["running"] is False
