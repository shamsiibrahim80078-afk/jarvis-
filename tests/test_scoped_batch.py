"""Test scoped phantom batch: detect tab, range, paste onto credentials rows."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jarvis.tools.api_pipeline import (
    is_batch_api_command,
    parse_batch_scope,
    paste_apis_to_sheet,
    run_batch_from_sheet,
)
from jarvis.tools.sheets import discover_sheet_tabs, resolve_best_tab
from jarvis.tools.workflows import get_link


def main() -> int:
    url = get_link("api_sheet")
    assert url, "no api_sheet"

    scope = parse_batch_scope(
        "get phantom api tools apis from 1590 to the end and paste"
    )
    print("SCOPE", scope)
    assert scope["tab_hint"]
    assert scope["start_row"] == 1590
    assert scope["end_row"] is None
    assert is_batch_api_command(
        "get phantom api tools apis from 1590 to the end and paste"
    )

    tabs = discover_sheet_tabs(url, force=True)
    print("TABS", [(t["gid"], t["kind"], t["rows"]) for t in tabs])
    cred = resolve_best_tab(url, hint="phantom api tools", prefer="credentials")
    print("CRED", cred)
    assert cred and cred["kind"] == "credentials"

    # Out-of-range should explain, not paste on summary
    msg = run_batch_from_sheet("get phantom apis from 1590 to the end and paste")
    print("OUT_OF_RANGE:\n", msg[:400])
    assert "past the end" in msg.lower() or "only has rows" in msg.lower()

    # Live: paste registry keys into a small empty range on credentials tab
    msg2 = run_batch_from_sheet(
        "get phantom apis from 157 to 160 and paste first 3"
    )
    print("LIVE_RANGE:\n", msg2[:800])
    assert "credentials tab" in msg2.lower() or "gid=" in msg2.lower()
    assert "summary" not in msg2.lower() or "credentials" in msg2.lower()
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
