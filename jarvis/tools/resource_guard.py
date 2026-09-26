"""Resource pressure guard — concurrency control for ~4 GB Windows laptops.

Root cause of past OOMs: concurrent Mira encode + screen-record + growth/ambient,
not Mira existing as a product.

Policy (Owner 2026-09-24):
- Prefer ONE heavy job at a time (mira XOR screen_record; growth defers).
- Soften memory thresholds so typical 4 GB load does not make Mira unusable.
- Hard-fail only when allocation is genuinely unsafe even after soft reclaim,
  or when another heavy job is already running.
"""

from __future__ import annotations

import gc
import os
from typing import Any


def _hard_mem_pct() -> float:
    """Only block at near-exhaustion (default 98%)."""
    try:
        return max(94.0, min(99.5, float(os.getenv("JARVIS_MEM_HARD_PCT") or "98")))
    except (TypeError, ValueError):
        return 98.0


def _hard_avail_mb() -> float:
    """Only block when free RAM is critically tiny (default 120 MB)."""
    try:
        return max(80.0, float(os.getenv("JARVIS_MEM_HARD_AVAIL_MB") or "120"))
    except (TypeError, ValueError):
        return 120.0


def _soft_mem_pct() -> float:
    """Advisory pressure — still allow job, force sequential/low-RAM hints."""
    try:
        return max(70.0, min(97.0, float(os.getenv("JARVIS_MEM_SOFT_PCT") or "88")))
    except (TypeError, ValueError):
        return 88.0


def _cpu_pressure_pct() -> float:
    try:
        return max(70.0, min(100.0, float(os.getenv("JARVIS_CPU_PRESSURE_PCT") or "97")))
    except (TypeError, ValueError):
        return 97.0


# Back-compat aliases used by older tests/callers
def _mem_block_pct() -> float:
    return _hard_mem_pct()


def _mem_avail_block_mb() -> float:
    return _hard_avail_mb()


def snapshot() -> dict[str, Any]:
    """Non-blocking-ish resource snapshot."""
    out: dict[str, Any] = {
        "ok": True,
        "cpu_percent": None,
        "mem_percent": None,
        "mem_available_mb": None,
        "mem_total_mb": None,
        "screen_recording": False,
        "mira_running": False,
        "pressure": "ok",
    }
    try:
        import psutil

        out["cpu_percent"] = float(psutil.cpu_percent(interval=None))
        mem = psutil.virtual_memory()
        out["mem_percent"] = float(mem.percent)
        out["mem_available_mb"] = round(float(mem.available) / (1024 * 1024), 1)
        out["mem_total_mb"] = round(float(mem.total) / (1024 * 1024), 1)
    except Exception as exc:
        out["ok"] = False
        out["error"] = f"{type(exc).__name__}: {exc}"[:120]
    try:
        from jarvis.tools.screen_record import status as rec_status

        out["screen_recording"] = bool((rec_status() or {}).get("running"))
    except Exception:
        pass
    try:
        from jarvis.tools import mira_jobs

        st = mira_jobs._read()  # noqa: SLF001
        out["mira_running"] = bool(st.get("running"))
    except Exception:
        pass

    mem_pct = out.get("mem_percent")
    avail = out.get("mem_available_mb")
    if mem_pct is not None and float(mem_pct) >= _hard_mem_pct():
        out["pressure"] = "hard"
    elif avail is not None and float(avail) < _hard_avail_mb():
        out["pressure"] = "hard"
    elif mem_pct is not None and float(mem_pct) >= _soft_mem_pct():
        out["pressure"] = "soft"
    return out


def soft_reclaim() -> dict[str, Any]:
    """Best-effort free standby pages + GC before a heavy job. Never raises."""
    info: dict[str, Any] = {"gc": 0, "trimmed": 0}
    try:
        info["gc"] = int(gc.collect() or 0)
    except Exception:
        pass
    try:
        import ctypes

        import psutil

        k32 = ctypes.windll.kernel32
        psapi = ctypes.windll.psapi
        flags = 0x0100 | 0x0400
        skip = {
            "system",
            "registry",
            "smss.exe",
            "csrss.exe",
            "wininit.exe",
            "services.exe",
            "lsass.exe",
            "svchost.exe",
            "fontdrvhost.exe",
            "dwm.exe",
            "python.exe",
            "pythonw.exe",
            "cursor.exe",
        }
        n = 0
        for p in psutil.process_iter(["pid", "name"]):
            try:
                name = (p.info["name"] or "").lower()
                if name in skip or not name:
                    continue
                h = k32.OpenProcess(flags, False, int(p.info["pid"]))
                if h:
                    if psapi.EmptyWorkingSet(h):
                        n += 1
                    k32.CloseHandle(h)
            except Exception:
                continue
        info["trimmed"] = n
    except Exception as exc:
        info["trim_error"] = f"{type(exc).__name__}: {exc}"[:80]
    info["after"] = snapshot()
    return info


def can_start_heavy_job(*, kind: str = "mira") -> tuple[bool, str, dict[str, Any]]:
    """Return (ok, reason_if_blocked, snapshot).

    ``kind``: mira | screen_record | growth

    Blocks concurrent heavy jobs always.
    Memory hard-fail only at near-exhaustion (after optional reclaim for mira).
    """
    kind = (kind or "mira").strip().lower()
    snap = snapshot()

    # Concurrency first — this is what OOM'd the machine historically
    if kind == "mira" and snap.get("screen_recording"):
        return (
            False,
            (
                "Screen recording is already running. Only one heavy media job "
                "at a time on this PC — stop the screen record, then ask Mira."
            ),
            snap,
        )
    if kind == "screen_record" and snap.get("mira_running"):
        return (
            False,
            (
                "Mira is already encoding. Only one heavy media job at a time — "
                "wait for Mira to finish, then record."
            ),
            snap,
        )
    if kind == "growth" and (snap.get("mira_running") or snap.get("screen_recording")):
        return (
            False,
            "Growth deferred while Mira or screen recording is active.",
            snap,
        )
    if kind == "mira" and snap.get("mira_running"):
        return (
            False,
            "Mira is already running a job. Wait for it to finish.",
            snap,
        )

    mem_pct = snap.get("mem_percent")
    avail = snap.get("mem_available_mb")
    cpu = snap.get("cpu_percent")

    hard = False
    if mem_pct is not None and float(mem_pct) >= _hard_mem_pct():
        hard = True
    if avail is not None and float(avail) < _hard_avail_mb():
        hard = True

    if hard and kind in ("mira", "screen_record"):
        # Soft reclaim once, then re-check — do not refuse on first soft spike
        reclaim = soft_reclaim()
        snap = reclaim.get("after") or snapshot()
        mem_pct = snap.get("mem_percent")
        avail = snap.get("mem_available_mb")
        still_hard = False
        if mem_pct is not None and float(mem_pct) >= _hard_mem_pct():
            still_hard = True
        if avail is not None and float(avail) < _hard_avail_mb():
            still_hard = True
        if still_hard:
            return (
                False,
                (
                    f"Memory is exhausted even after cleanup "
                    f"({mem_pct:.0f}% used, ~{avail:.0f} MB free). "
                    f"Cannot safely allocate for {kind}. Close other apps, then retry."
                ),
                snap,
            )
        # Recovered enough — continue (sequential / low-RAM path expected)
        snap["pressure"] = "soft"
        snap["reclaimed"] = True

    # CPU+mem both extreme: brief defer (not permanent refuse)
    if (
        cpu is not None
        and mem_pct is not None
        and float(cpu) >= _cpu_pressure_pct()
        and float(mem_pct) >= 96.0
    ):
        return (
            False,
            (
                f"CPU {cpu:.0f}% and memory {mem_pct:.0f}% — wait a few seconds for "
                f"load to drop, then retry {kind}."
            ),
            snap,
        )

    return True, "", snap
