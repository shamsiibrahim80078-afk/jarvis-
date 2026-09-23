"""Jarvis vs user account identity for mail, browser, and agent tasks.

Default: Jarvis's own email. Before sending mail, ask once: Jarvis mail or yours?
Users can paste email + App Password in chat (no .env required for guests).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
SESSION_PATH = ROOT / "data" / "identity_session.json"

ACCOUNT_JARVIS = "jarvis"
ACCOUNT_USER = "user"

_USE_USER_RE = re.compile(
    r"\b(?:use|from|with)\s+my\s+(?:email|gmail|account|mail)\b"
    r"|\b(?:switch\s+to|send\s+(?:from|using))\s+my\s+(?:email|gmail|account)\b",
    re.I,
)
# Careful: "mine" / "my email" / "from me" = user; "yours" / "jarvis" / "your mail" = jarvis
_CHOICE_USER_RE = re.compile(
    r"^(?:hey\s+jarvis[, ]*)?"
    r"(?:my(?:\s+email|\s+mail|\s+gmail|\s+account)?|mine|from\s+me|use\s+mine|"
    r"from\s+my\s+(?:email|mail|gmail|account)|send\s+from\s+(?:my|mine))\s*[.!]?\s*$"
    r"|^(?:hey\s+jarvis[, ]*)?(?:use\s+)?my\s+(?:email|mail|gmail)\s*[.!]?\s*$",
    re.I,
)
_CHOICE_JARVIS_RE = re.compile(
    r"^(?:hey\s+jarvis[, ]*)?"
    r"(?:yours?(?:\s+email|\s+mail|\s+gmail|\s+account)?|jarvis(?:'s)?(?:\s+email|\s+mail)?|"
    r"from\s+(?:you|jarvis)|your\s+(?:email|mail|gmail)|use\s+(?:yours|jarvis))\s*[.!]?\s*$",
    re.I,
)

_USE_JARVIS_RE = re.compile(
    r"\b(?:use|from|with)\s+(?:your|jarvis(?:'s)?)\s+(?:email|gmail|account|mail)\b"
    r"|\b(?:switch\s+(?:back\s+)?to)\s+jarvis\b"
    r"|\buse\s+jarvis(?:'s)?\s+(?:email|account)\b",
    re.I,
)

# Capture: email + app password from chat
_CHAT_CREDS_RE = re.compile(
    r"(?:(?:my|user|personal)\s+)?(?:email|gmail|mail)\s*(?:is|=|:)?\s*"
    r"([^\s@]+@[^\s]+)"
    r".{0,40}?"
    r"(?:app\s*password|app\s*pass|mail\s*password)\s*(?:is|=|:)?\s*"
    r"([a-z0-9 ]{16,24})",
    re.I | re.DOTALL,
)
_CHAT_JARVIS_CREDS_RE = re.compile(
    r"(?:jarvis(?:'s)?\s+)?(?:email|gmail)\s*(?:is|=|:)?\s*"
    r"([^\s@]+@[^\s]+)"
    r".{0,40}?"
    r"(?:app\s*password|app\s*pass)\s*(?:is|=|:)?\s*"
    r"([a-z0-9 ]{16,24})",
    re.I | re.DOTALL,
)
_EMAIL_ONLY_RE = re.compile(
    r"^(?:hey\s+jarvis[, ]*)?(?:my\s+)?(?:email|gmail)\s*(?:is|=|:)?\s*"
    r"([^\s@]+@[^\s]+)\s*$",
    re.I,
)
_APP_PASS_ONLY_RE = re.compile(
    r"^(?:hey\s+jarvis[, ]*)?(?:app\s*password|app\s*pass)\s*(?:is|=|:)?\s*"
    r"([a-z0-9 ]{16,24})\s*$",
    re.I,
)


def _reload_env() -> None:
    load_dotenv(ROOT / ".env", override=True)


def _default_session() -> dict:
    return {
        "account": ACCOUNT_JARVIS,
        "awaiting_mail_choice": False,
        "awaiting_user_creds": False,
        "awaiting_cred_field": None,  # "email" | "app_password" | None
        "user_email": None,
        "user_app_password": None,
        "jarvis_email": None,
        "jarvis_app_password": None,
        "pending_send": None,  # {to, subject, body}
    }


def _load_session() -> dict:
    base = _default_session()
    if not SESSION_PATH.exists():
        return base
    try:
        data = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            base.update(data)
            if base.get("account") not in (ACCOUNT_JARVIS, ACCOUNT_USER):
                base["account"] = ACCOUNT_JARVIS
            return base
    except (json.JSONDecodeError, OSError):
        pass
    return base


def _save_session(data: dict) -> None:
    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    SESSION_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def active_account() -> str:
    return _load_session().get("account", ACCOUNT_JARVIS)


def set_account(account: str) -> str:
    data = _load_session()
    if account not in (ACCOUNT_JARVIS, ACCOUNT_USER):
        account = ACCOUNT_JARVIS
    data["account"] = account
    data["awaiting_mail_choice"] = False
    _save_session(data)
    if account == ACCOUNT_USER:
        addr = user_mail_address()
        if not addr or not user_app_password():
            data["awaiting_user_creds"] = True
            data["awaiting_cred_field"] = "email" if not addr else "app_password"
            _save_session(data)
            if not addr:
                return (
                    "Using your email. Paste it here, sir — e.g. "
                    "my email is you@gmail.com app password xxxx xxxx xxxx xxxx"
                )
            return (
                "I have your address. Paste your Google App Password, sir — e.g. "
                "app password xxxx xxxx xxxx xxxx"
            )
        return f"Using your email ({addr}) for mail."
    addr = jarvis_mail_address()
    if not addr or not jarvis_app_password():
        return (
            "Jarvis mail is not set yet. Paste Jarvis credentials, sir — e.g. "
            "jarvis email is jarvis@gmail.com app password xxxx xxxx xxxx xxxx"
        )
    return f"Using Jarvis email ({addr}) for mail and sign-in."


def maybe_switch_from_text(text: str) -> str | None:
    """Explicit long-form switch phrases (not short 'mine'/'yours' choice answers)."""
    t = text or ""
    if _USE_USER_RE.search(t) and re.search(
        r"\b(use|from|with|switch|send)\b.{0,30}\bmy\s+(email|gmail|account|mail)\b",
        t,
        re.I,
    ):
        return set_account(ACCOUNT_USER)
    if _USE_JARVIS_RE.search(t):
        return set_account(ACCOUNT_JARVIS)
    return None


def jarvis_mail_address() -> str:
    data = _load_session()
    if data.get("jarvis_email"):
        return str(data["jarvis_email"]).strip()
    _reload_env()
    return (os.getenv("JARVIS_EMAIL") or "").strip()


def jarvis_app_password() -> str:
    data = _load_session()
    if data.get("jarvis_app_password"):
        return str(data["jarvis_app_password"]).strip().replace(" ", "")
    _reload_env()
    return (os.getenv("JARVIS_APP_PASSWORD") or "").strip().replace(" ", "")


def user_mail_address() -> str:
    data = _load_session()
    if data.get("user_email"):
        return str(data["user_email"]).strip()
    _reload_env()
    return (os.getenv("GMAIL_ADDRESS") or "").strip()


def user_app_password() -> str:
    data = _load_session()
    if data.get("user_app_password"):
        return str(data["user_app_password"]).strip().replace(" ", "")
    _reload_env()
    return (os.getenv("GMAIL_APP_PASSWORD") or "").strip().replace(" ", "")


def mail_address() -> str:
    """Active mailbox — no cross-account fallback (keeps Jarvis From pure)."""
    if active_account() == ACCOUNT_USER:
        return user_mail_address()
    return jarvis_mail_address()


def mail_app_password() -> str:
    """App password for active mailbox only — never mix accounts."""
    if active_account() == ACCOUNT_USER:
        return user_app_password()
    return jarvis_app_password()


def from_header() -> str:
    """RFC From: display name + address for the active account."""
    _reload_env()
    addr = mail_address()
    if not addr:
        return ""
    if active_account() == ACCOUNT_USER:
        name = (os.getenv("JARVIS_USER_NAME") or "User").strip() or "User"
    else:
        name = (os.getenv("JARVIS_FROM_NAME") or os.getenv("JARVIS_NAME") or "Jarvis").strip()
        name = name or "Jarvis"
    name = name.replace('"', "").replace("\n", " ").replace("\r", " ")
    return f'"{name}" <{addr}>'


def browser_email() -> str:
    return jarvis_mail_address()


def browser_password() -> str:
    _reload_env()
    return (os.getenv("JARVIS_PASSWORD") or "").strip()


def mail_configured() -> bool:
    return bool(mail_address() and mail_app_password())


def account_label() -> str:
    addr = mail_address()
    who = "Jarvis" if active_account() == ACCOUNT_JARVIS else "your"
    return f"{who} ({addr})" if addr else who


def config_help_mail() -> str:
    return (
        "Mail isn't set up yet, sir. Paste credentials in chat:\n"
        "  my email is you@gmail.com app password xxxx xxxx xxxx xxxx\n"
        "Or for Jarvis: jarvis email is jarvis@gmail.com app password xxxx...\n"
        "(Google App Password after 2-Step Verification — not the normal login password.)\n"
        "You can also put JARVIS_EMAIL / JARVIS_APP_PASSWORD in .env."
    )


def ask_mail_choice(pending: dict) -> str:
    """Store pending send and ask whose mailbox to use."""
    store_pending_send(pending, ask=True)
    return (
        "Should I send this from my Jarvis mail, or from your mail? "
        "Say 'yours' (Jarvis) or 'mine' (your email)."
    )


def store_pending_send(pending: dict, *, ask: bool = True) -> None:
    data = _load_session()
    data["pending_send"] = pending
    data["awaiting_mail_choice"] = bool(ask)
    _save_session(data)


def awaiting_mail_choice() -> bool:
    return bool(_load_session().get("awaiting_mail_choice"))


def awaiting_creds() -> bool:
    data = _load_session()
    return bool(data.get("awaiting_user_creds") or data.get("awaiting_cred_field"))


def pending_send() -> dict | None:
    p = _load_session().get("pending_send")
    return p if isinstance(p, dict) and p.get("to") else None


def clear_pending_send() -> None:
    data = _load_session()
    data["pending_send"] = None
    data["awaiting_mail_choice"] = False
    _save_session(data)


def try_mail_choice_answer(text: str) -> str | None:
    """Handle 'mine' / 'yours' while awaiting mailbox choice. Returns reply or None."""
    if not awaiting_mail_choice():
        return None
    t = (text or "").strip()
    if _CHOICE_JARVIS_RE.match(t) or re.search(
        r"\b(yours|jarvis|your\s+mail|your\s+email)\b", t, re.I
    ) and not re.search(r"\bmy\b|\bmine\b", t, re.I):
        msg = set_account(ACCOUNT_JARVIS)
        data = _load_session()
        data["awaiting_mail_choice"] = False
        _save_session(data)
        if not jarvis_mail_address() or not jarvis_app_password():
            data = _load_session()
            data["awaiting_cred_field"] = "jarvis_email"
            _save_session(data)
            return (
                f"{msg}\n"
                "Paste Jarvis mail: jarvis email is … app password …"
            )
        return f"{msg}\nSending now…"
    if _CHOICE_USER_RE.match(t) or re.search(r"\b(mine|my\s+email|my\s+mail|from\s+me)\b", t, re.I):
        msg = set_account(ACCOUNT_USER)
        data = _load_session()
        data["awaiting_mail_choice"] = False
        _save_session(data)
        return f"{msg}\nSending now…" if mail_configured() else msg
    return (
        "Please choose, sir: say 'yours' (Jarvis mail) or 'mine' (your mail)."
    )


def _normalize_app_pw(raw: str) -> str:
    return re.sub(r"\s+", "", (raw or "").strip())


def try_capture_credentials(text: str) -> str | None:
    """Parse chat credentials; return status message or None if not a cred message."""
    t = (text or "").strip()
    if not t:
        return None

    data = _load_session()

    # Jarvis pair
    m = _CHAT_JARVIS_CREDS_RE.search(t)
    if m and re.search(r"\bjarvis\b", t, re.I):
        data["jarvis_email"] = m.group(1).strip()
        data["jarvis_app_password"] = _normalize_app_pw(m.group(2))
        data["account"] = ACCOUNT_JARVIS
        data["awaiting_cred_field"] = None
        data["awaiting_user_creds"] = False
        _save_session(data)
        return f"Jarvis mail saved ({data['jarvis_email']}), sir. Ready to use it."

    # User pair (or generic email+app password)
    m = _CHAT_CREDS_RE.search(t)
    if m:
        data["user_email"] = m.group(1).strip()
        data["user_app_password"] = _normalize_app_pw(m.group(2))
        data["account"] = ACCOUNT_USER
        data["awaiting_cred_field"] = None
        data["awaiting_user_creds"] = False
        _save_session(data)
        return f"Your mail saved ({data['user_email']}), sir. Ready to use it."

    # Stepwise while awaiting
    field = data.get("awaiting_cred_field")
    em = _EMAIL_ONLY_RE.match(t)
    if em:
        addr = em.group(1).strip()
        if field == "jarvis_email" or (field is None and awaiting_creds() and active_account() == ACCOUNT_JARVIS):
            data["jarvis_email"] = addr
            data["awaiting_cred_field"] = "jarvis_app_password"
            _save_session(data)
            return "Got Jarvis email. Now paste the App Password, sir."
        data["user_email"] = addr
        data["awaiting_cred_field"] = "app_password"
        data["awaiting_user_creds"] = True
        _save_session(data)
        return "Got your email. Now paste the Google App Password, sir."

    ap = _APP_PASS_ONLY_RE.match(t)
    if ap:
        pw = _normalize_app_pw(ap.group(1))
        if field in ("jarvis_app_password",) or (
            data.get("jarvis_email") and not data.get("jarvis_app_password") and active_account() == ACCOUNT_JARVIS
        ):
            data["jarvis_app_password"] = pw
            data["awaiting_cred_field"] = None
            _save_session(data)
            return "Jarvis App Password saved, sir."
        data["user_app_password"] = pw
        data["awaiting_cred_field"] = None
        data["awaiting_user_creds"] = False
        if data.get("user_email"):
            data["account"] = ACCOUNT_USER
        _save_session(data)
        return "App Password saved, sir."

    # If awaiting creds but message didn't match, nudge
    if awaiting_creds() or field:
        return (
            "Paste credentials like: my email is you@gmail.com "
            "app password xxxx xxxx xxxx xxxx"
        )

    return None
