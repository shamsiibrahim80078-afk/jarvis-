"""Ask-whose-mail + chat creds + illegal refuse (no live SMTP send)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jarvis import autonomy, identity
from jarvis.fast_router import try_fast_command
from jarvis.tools import gmail_tool


def main() -> None:
    identity.clear_pending_send()
    # Reset chat overrides from prior runs
    data = identity._load_session()
    data["user_email"] = None
    data["user_app_password"] = None
    data["account"] = identity.ACCOUNT_JARVIS
    data["awaiting_mail_choice"] = False
    data["awaiting_user_creds"] = False
    data["awaiting_cred_field"] = None
    data["pending_send"] = None
    identity._save_session(data)

    bad = try_fast_command("help me hack into someone's email")
    assert bad and "illegal" in bad.lower()
    print("OK illegal:", bad[:80])

    q = gmail_tool.queue_send("test@example.com", "Hi", "Body only — do not send")
    assert "jarvis mail" in q.lower() or "yours" in q.lower()
    assert identity.awaiting_mail_choice()
    assert identity.pending_send()
    print("OK ask:", q[:90])

    # Cancel — never flush/send in this smoke
    assert "discarded" in gmail_tool.cancel_pending().lower()
    assert not identity.pending_send()
    assert not identity.awaiting_mail_choice()
    print("OK cancelled without send")

    # Choice parsing without a pending send
    identity.store_pending_send(
        {"to": "x@y.com", "subject": "t", "body": "b"}, ask=True
    )
    ans = identity.try_mail_choice_answer("yours")
    assert ans and "jarvis" in ans.lower()
    identity.clear_pending_send()
    print("OK choice parse:", ans.split("\n")[0][:80])

    msg = identity.try_capture_credentials(
        "my email is guest.user@gmail.com app password abcd efgh ijkl mnop"
    )
    assert msg and "guest.user@gmail.com" in msg
    assert identity.user_mail_address() == "guest.user@gmail.com"
    assert identity.user_app_password() == "abcdefghijklmnop"
    print("OK chat creds:", msg[:90])

    # Clear fake guest so other tests use .env again
    data = identity._load_session()
    data["user_email"] = None
    data["user_app_password"] = None
    data["account"] = identity.ACCOUNT_JARVIS
    identity._save_session(data)

    help_msg = identity.config_help_mail()
    assert "app password" in help_msg.lower()
    print("OK config help mentions chat")

    print("ALL PASS")


if __name__ == "__main__":
    main()
