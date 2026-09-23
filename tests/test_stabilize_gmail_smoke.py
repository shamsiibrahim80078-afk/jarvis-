"""Stabilize Phase 1 routing + Gmail identity/autonomy smoke (no live mail send)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jarvis import autonomy, identity
from jarvis.tools.api_intent import is_api_hunt_intent
from jarvis.tools.api_pipeline import is_batch_api_command, parse_batch_scope
from jarvis.tools import gmail_tool
from jarvis.tools.hunt_bus import force_reset, is_running


def main() -> int:
    force_reset()
    assert not is_running()

    cases = [
        ("get phantom apis from 22 to 23 and paste", True, False),
        ("get phantom api tools apis from 1590 to the end and paste", True, False),
        ("get me eleven labs api key", False, True),
        ("how many apis are still there", False, False),
    ]
    for msg, expect_batch, expect_hunt in cases:
        b, h = is_batch_api_command(msg), is_api_hunt_intent(msg)
        assert b == expect_batch, f"{msg}: batch={b}"
        assert h == expect_hunt, f"{msg}: hunt={h}"
        print("OK route", msg[:40], "batch", b, "hunt", h)

    scope = parse_batch_scope("get phantom apis from 150 to 160 and paste")
    assert scope["start_row"] == 150 and scope["end_row"] == 160
    print("OK scope", scope)

    help_msg = gmail_tool.config_help()
    assert "JARVIS_APP_PASSWORD" in help_msg
    print("OK gmail config help")

    assert identity.active_account() in ("jarvis", "user")
    print("OK identity", identity.active_account(), identity.mail_address() or "(none)")

    assert autonomy.is_hard_pause("buy this api plan now")
    assert not autonomy.is_hard_pause("check my unread email")
    msg = autonomy.pause_message("purchase credits")
    assert "yes proceed" in msg.lower()
    assert autonomy.take_pending_if_confirmed("yes proceed") == "purchase credits"
    print("OK autonomy hard-pause")

    import importlib.util
    spec = importlib.util.spec_from_file_location("plugins.gmail", ROOT / "plugins" / "gmail.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    resp = mod.handle("check my unread email")
    assert resp and (
        "unread" in resp.lower()
        or "inbox" in resp.lower()
        or "JARVIS_APP_PASSWORD" in resp
        or "not configured" in resp.lower()
        or "App Password" in resp
    )
    print("OK plugin", resp[:80])

    # Compose wizard + cancel (never sends)
    if gmail_tool.configured():
        start = gmail_tool.start_compose("test@example.com")
        assert "subject" in start.lower()
        assert gmail_tool.composing()
        assert "discarded" in gmail_tool.cancel_pending().lower()
        assert not gmail_tool.composing()
        print("OK compose/cancel (no send)")
    else:
        d = gmail_tool.send_email("test@example.com", "Hi", "Hello")
        assert "JARVIS_APP_PASSWORD" in d or "not configured" in d.lower()
        print("OK send blocked until app password")

    print("ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
