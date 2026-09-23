"""Gmail via IMAP/SMTP — Jarvis identity by default; auto-send when compose is complete.

Credentials from jarvis.identity (JARVIS_* default; GMAIL_* when "use my email").
Never uses JARVIS_PASSWORD for IMAP/SMTP — App Password only.
"""

from __future__ import annotations

import email
import imaplib
import json
import re
import smtplib
import ssl
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from pathlib import Path

from jarvis import identity

ROOT = Path(__file__).resolve().parents[2]
PENDING_PATH = ROOT / "data" / "gmail_pending.json"
COMPOSE_PATH = ROOT / "data" / "gmail_compose.json"


def _addr() -> str:
    return identity.mail_address()


def _app_password() -> str:
    return identity.mail_app_password()


def configured() -> bool:
    return identity.mail_configured()


def config_help() -> str:
    return identity.config_help_mail()


def _decode_mime(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _imap_connect() -> imaplib.IMAP4_SSL:
    mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    mail.login(_addr(), _app_password())
    return mail


def list_unread(limit: int = 5) -> str:
    if not configured():
        return config_help()
    limit = max(1, min(int(limit), 15))
    label = identity.account_label()
    try:
        mail = _imap_connect()
        mail.select("INBOX")
        status, data = mail.search(None, "UNSEEN")
        if status != "OK":
            mail.logout()
            return "Could not search inbox, sir."
        ids = data[0].split() if data and data[0] else []
        if not ids:
            mail.logout()
            return f"No unread mail on {label}, sir. Inbox is clear."
        newest = list(reversed(ids))[:limit]
        lines = [f"{len(ids)} unread on {label}. Showing latest {len(newest)}:"]
        for i, uid in enumerate(newest, 1):
            st, msg_data = mail.fetch(uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if st != "OK" or not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0][1]
            if isinstance(raw, bytes):
                hdr = email.message_from_bytes(raw)
            else:
                continue
            frm = _decode_mime(hdr.get("From"))
            subj = _decode_mime(hdr.get("Subject")) or "(no subject)"
            date = hdr.get("Date") or ""
            try:
                date = parsedate_to_datetime(date).strftime("%b %d %H:%M")
            except Exception:
                date = date[:16]
            lines.append(f"{i}. [{date}] {frm} — {subj}")
        mail.logout()
        return "\n".join(lines)
    except imaplib.IMAP4.error as exc:
        err = str(exc).lower()
        if "invalid credentials" in err or "authentication failed" in err:
            return (
                "Gmail login failed, sir. Set JARVIS_APP_PASSWORD to a Google App Password "
                "(2-Step Verification required). Do not use the normal login password."
            )
        return f"Gmail IMAP error, sir: {exc}"
    except Exception as exc:
        return f"Gmail error, sir: {exc}"


def _save_pending(to: str, subject: str, body: str) -> None:
    PENDING_PATH.parent.mkdir(parents=True, exist_ok=True)
    PENDING_PATH.write_text(
        json.dumps({"to": to, "subject": subject, "body": body}, indent=2),
        encoding="utf-8",
    )


def _load_pending() -> dict | None:
    if not PENDING_PATH.exists():
        return None
    try:
        data = json.loads(PENDING_PATH.read_text(encoding="utf-8"))
        if data.get("to") and data.get("subject") is not None:
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _clear_pending() -> None:
    try:
        if PENDING_PATH.exists():
            PENDING_PATH.unlink()
    except OSError:
        pass


def _load_compose() -> dict | None:
    if not COMPOSE_PATH.exists():
        return None
    try:
        data = json.loads(COMPOSE_PATH.read_text(encoding="utf-8"))
        if data.get("to") and data.get("step") in ("subject", "body"):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _save_compose(data: dict) -> None:
    COMPOSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    COMPOSE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _clear_compose() -> None:
    try:
        if COMPOSE_PATH.exists():
            COMPOSE_PATH.unlink()
    except OSError:
        pass


def composing() -> bool:
    return _load_compose() is not None


def start_compose(to: str) -> str:
    """Begin multi-step compose: ask subject, then body, then auto-send."""
    if not configured():
        return config_help()
    to = to.strip()
    if not to or "@" not in to:
        return "Need a valid recipient email, sir."
    _clear_pending()
    _save_compose({"to": to, "subject": "", "step": "subject"})
    return f"Drafting to {to} from {identity.account_label()}. What's the subject?"


def continue_compose(text: str) -> str | None:
    """Feed the next line into an in-progress compose. Then ask whose mail / send."""
    state = _load_compose()
    if not state:
        return None
    line = text.strip()
    if not line:
        if state["step"] == "subject":
            return "What's the subject, sir?"
        return "What's the message body, sir?"

    if state["step"] == "subject":
        m = re.match(r"(?:subject|subj)\s+(.+)$", line, re.I)
        subject = (m.group(1) if m else line).strip() or "(no subject)"
        state["subject"] = subject
        state["step"] = "body"
        _save_compose(state)
        return f"Subject set to '{subject}'. What's the message body?"

    m = re.match(r"(?:body|message|saying)\s+(.+)$", line, re.I | re.DOTALL)
    body = (m.group(1) if m else line).strip()
    to = state["to"]
    subject = state.get("subject") or "(no subject)"
    _clear_compose()
    return queue_send(to, subject, body)


def cancel_pending() -> str:
    had = bool(_load_pending() or _load_compose() or identity.pending_send())
    _clear_pending()
    _clear_compose()
    identity.clear_pending_send()
    if not had:
        return "No draft to cancel, sir."
    return "Draft discarded, sir."


def parse_compose(text: str) -> tuple[str, str, str] | None:
    """Parse 'email X subject Y body Z' / 'send email to X ...'."""
    lower = text.strip()
    m = re.search(
        r"(?:email|mail|send\s+(?:an?\s+)?email(?:\s+to)?)\s+"
        r"([^\s]+@[^\s]+)\s+"
        r"(?:subject|subj)\s+(.+?)\s+"
        r"(?:body|message|saying)\s+(.+)$",
        lower,
        re.I | re.DOTALL,
    )
    if m:
        return m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
    m = re.search(
        r"(?:email|mail)\s+([^\s]+@[^\s]+)\s+(.+)$",
        lower,
        re.I | re.DOTALL,
    )
    if m:
        rest = m.group(2).strip()
        sm = re.search(r"subject\s+(.+?)(?:\s+body\s+|\s+message\s+)(.+)$", rest, re.I | re.DOTALL)
        if sm:
            return m.group(1).strip(), sm.group(1).strip(), sm.group(2).strip()
        return m.group(1).strip(), "(no subject)", rest
    return None


def parse_recipient_only(text: str) -> str | None:
    """Match 'email someone@x.com' with nothing else."""
    m = re.search(
        r"^(?:hey\s+jarvis[, ]*)?(?:email|mail|send\s+(?:an?\s+)?email(?:\s+to)?)\s+"
        r"([^\s]+@[^\s]+)\s*$",
        text.strip(),
        re.I,
    )
    return m.group(1).strip() if m else None


def queue_send(to: str, subject: str, body: str, *, skip_choice: bool = False) -> str:
    """Ask whose mailbox, then send — or send immediately if choice already known."""
    to = to.strip()
    subject = (subject or "").strip() or "(no subject)"
    body = (body or "").strip()
    if not to or "@" not in to:
        return "Need a valid recipient email, sir."
    if not body:
        return "Need a message body, sir."
    pending = {"to": to, "subject": subject, "body": body}
    if not skip_choice:
        return identity.ask_mail_choice(pending)
    identity.store_pending_send(pending, ask=False)
    return flush_pending_send()


def flush_pending_send() -> str:
    """Send identity.pending_send once account + creds are ready."""
    pending = identity.pending_send()
    if not pending:
        return "No mail waiting to send, sir."
    if identity.awaiting_mail_choice():
        return (
            "Should I send from my Jarvis mail, or from your mail? "
            "Say 'yours' (Jarvis) or 'mine' (your email)."
        )
    if not configured():
        if identity.active_account() == identity.ACCOUNT_USER:
            data = identity._load_session()
            data["awaiting_user_creds"] = True
            data["awaiting_cred_field"] = (
                "email" if not identity.user_mail_address() else "app_password"
            )
            identity._save_session(data)
        return config_help()
    to, subject, body = pending["to"], pending["subject"], pending["body"]
    identity.clear_pending_send()
    return send_email(to, subject, body, _already_queued=True)


def send_email(to: str, subject: str, body: str, _already_queued: bool = False) -> str:
    """Send from the active identity. Prefer queue_send() so we ask whose mail."""
    if not _already_queued:
        return queue_send(to, subject, body)
    if not configured():
        return config_help()
    to = to.strip()
    subject = subject.strip() or "(no subject)"
    body = body.strip()
    if not to or "@" not in to:
        return "Need a valid recipient email, sir."
    if not body:
        return "Need a message body, sir."
    _clear_compose()
    _clear_pending()
    frm = _addr()
    from_hdr = identity.from_header() or frm
    if not frm:
        return config_help()
    # Hard guarantee: when Jarvis account, never send as personal Gmail
    if identity.active_account() == identity.ACCOUNT_JARVIS:
        expected = identity.jarvis_mail_address().lower()
        if frm.lower() != expected:
            return (
                f"Refusing to send, sir — Jarvis mailbox mismatch "
                f"({frm} vs {expected}). Check JARVIS_EMAIL in .env."
            )
    try:
        msg = EmailMessage()
        msg["From"] = from_hdr
        msg["To"] = to
        msg["Subject"] = subject
        msg["Reply-To"] = frm
        msg.set_content(body)
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as smtp:
            smtp.login(frm, _app_password())
            # envelope sender must match authenticated Jarvis/user address
            smtp.send_message(msg, from_addr=frm, to_addrs=[to])
        return f"Email sent to {to} from {frm}, sir."
    except smtplib.SMTPAuthenticationError:
        return (
            "SMTP auth failed, sir. Paste a Google App Password in chat "
            "(my email is … app password …) or set JARVIS_APP_PASSWORD in .env."
        )
    except Exception as exc:
        return f"Send failed, sir: {exc}"


def draft_email(to: str, subject: str, body: str) -> str:
    """Queue send (asks whose mail)."""
    return queue_send(to, subject, body)


def send_pending() -> str:
    """Send leftover pending draft or flush identity pending_send."""
    if identity.pending_send():
        return flush_pending_send()
    if not configured():
        return config_help()
    pending = _load_pending()
    if not pending:
        return "No draft waiting, sir. Say 'email someone@x.com subject ... body ...' to send."
    result = send_email(pending["to"], pending["subject"], pending["body"], _already_queued=True)
    _clear_pending()
    return result
