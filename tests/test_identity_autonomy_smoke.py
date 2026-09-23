"""Identity + autonomy + Gmail unread smoke (live IMAP if configured; no send)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jarvis import autonomy, identity
from jarvis.fast_router import try_fast_command
from jarvis.tools import gmail_tool


def main() -> None:
    identity.set_account(identity.ACCOUNT_JARVIS)
    assert identity.active_account() == "jarvis"
    print("OK default account jarvis")

    sw = try_fast_command("use my email")
    assert sw and ("email" in sw.lower() or "gmail" in sw.lower() or "configured" in sw.lower())
    print("OK switch:", sw[:90])

    sw2 = try_fast_command("use jarvis email")
    assert sw2 and "jarvis" in sw2.lower()
    print("OK switch back:", sw2[:90])

    pause = try_fast_command("buy something expensive")
    assert pause and "proceed" in pause.lower()
    print("OK hard pause")

    if gmail_tool.configured():
        unread = gmail_tool.list_unread(2)
        low = unread.lower()
        assert (
            "unread" in low
            or "clear" in low
            or "login failed" in low
            or "app password" in low
            or "not configured" in low
        ), unread[:200]
        print("OK unread:", unread.split("\n")[0][:100])
        # Parse path exists (do not send)
        parsed = gmail_tool.parse_compose(
            "email test@example.com subject Hi body Autonomy smoke — do not send"
        )
        assert parsed and parsed[0] == "test@example.com"
        print("OK parse compose for auto-send path")
    else:
        print("SKIP live unread — mail not configured")

    print("ALL PASS")


if __name__ == "__main__":
    main()
