"""Resource pressure guard — concurrency first; hard-fail only near exhaustion."""

from __future__ import annotations

from jarvis.tools import resource_guard


def test_snapshot_has_core_fields():
    snap = resource_guard.snapshot()
    assert "mem_percent" in snap
    assert "cpu_percent" in snap
    assert "screen_recording" in snap
    assert "mira_running" in snap
    assert "pressure" in snap


def test_soft_pressure_allows_mira(monkeypatch):
    """~4 GB typical load (96% / 400 MB free) must NOT refuse Mira."""
    soft_snap = {
        "ok": True,
        "cpu_percent": 40.0,
        "mem_percent": 96.0,
        "mem_available_mb": 400.0,
        "screen_recording": False,
        "mira_running": False,
        "pressure": "soft",
    }
    monkeypatch.setattr(resource_guard, "snapshot", lambda: dict(soft_snap))
    monkeypatch.setattr(
        resource_guard,
        "soft_reclaim",
        lambda: {"gc": 0, "trimmed": 0, "after": dict(soft_snap)},
    )
    ok, reason, snap = resource_guard.can_start_heavy_job(kind="mira")
    assert ok is True
    assert reason == ""
    assert snap["mem_percent"] == 96.0


def test_hard_exhaustion_blocks_after_reclaim(monkeypatch):
    """Only near-exhaustion (98%+ / &lt;120 MB) hard-fails after soft reclaim."""
    hard_snap = {
        "ok": True,
        "cpu_percent": 40.0,
        "mem_percent": 99.0,
        "mem_available_mb": 50.0,
        "screen_recording": False,
        "mira_running": False,
        "pressure": "hard",
    }
    monkeypatch.setattr(resource_guard, "snapshot", lambda: dict(hard_snap))
    monkeypatch.setattr(
        resource_guard,
        "soft_reclaim",
        lambda: {"gc": 1, "trimmed": 0, "after": dict(hard_snap)},
    )
    ok, reason, snap = resource_guard.can_start_heavy_job(kind="mira")
    assert ok is False
    assert "memory" in reason.lower() or "exhaust" in reason.lower()
    assert snap["mem_percent"] == 99.0


def test_blocks_mira_while_screen_recording(monkeypatch):
    monkeypatch.setattr(
        resource_guard,
        "snapshot",
        lambda: {
            "ok": True,
            "cpu_percent": 30.0,
            "mem_percent": 60.0,
            "mem_available_mb": 4000.0,
            "screen_recording": True,
            "mira_running": False,
        },
    )
    ok, reason, _ = resource_guard.can_start_heavy_job(kind="mira")
    assert ok is False
    assert "screen" in reason.lower()


def test_blocks_screen_record_while_mira(monkeypatch):
    monkeypatch.setattr(
        resource_guard,
        "snapshot",
        lambda: {
            "ok": True,
            "cpu_percent": 30.0,
            "mem_percent": 60.0,
            "mem_available_mb": 4000.0,
            "screen_recording": False,
            "mira_running": True,
        },
    )
    ok, reason, _ = resource_guard.can_start_heavy_job(kind="screen_record")
    assert ok is False
    assert "mira" in reason.lower()


def test_allows_when_healthy(monkeypatch):
    monkeypatch.setattr(
        resource_guard,
        "snapshot",
        lambda: {
            "ok": True,
            "cpu_percent": 20.0,
            "mem_percent": 55.0,
            "mem_available_mb": 5000.0,
            "screen_recording": False,
            "mira_running": False,
        },
    )
    ok, reason, _ = resource_guard.can_start_heavy_job(kind="mira")
    assert ok is True
    assert reason == ""
