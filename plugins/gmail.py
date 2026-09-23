"""Gmail plugin — ask whose mail, accept chat credentials, then send."""

from __future__ import annotations

import re

from jarvis import identity
from jarvis.tools import gmail_tool


def handle(text: str) -> str | None:
    lower = text.lower().strip()
    if not lower:
        return None

    # Chat credentials (highest priority when pasting secrets)
    creds = identity.try_capture_credentials(text)
    if creds:
        # If a send was waiting, flush after creds
        if identity.pending_send() and identity.mail_configured():
            return f"{creds}\n{gmail_tool.flush_pending_send()}"
        return creds

    # Mailbox choice: yours (Jarvis) / mine (user)
    if identity.awaiting_mail_choice():
        choice = identity.try_mail_choice_answer(text)
        if choice:
            if "Sending now" in choice or (
                identity.pending_send()
                and identity.mail_configured()
                and not identity.awaiting_mail_choice()
                and not identity.awaiting_creds()
            ):
                # Strip "Sending now…" then flush
                flushed = gmail_tool.flush_pending_send()
                # Avoid double "Sending now" noise
                prefix = choice.replace("Sending now…", "").strip()
                if prefix:
                    return f"{prefix}\n{flushed}"
                return flushed
            return choice

    # Still waiting on creds for a pending send
    if identity.awaiting_creds() and identity.pending_send():
        nudge = identity.try_capture_credentials(text)
        if nudge:
            if identity.mail_configured():
                return f"{nudge}\n{gmail_tool.flush_pending_send()}"
            return nudge

    # Explicit identity switch
    switched = identity.maybe_switch_from_text(text)
    if switched and re.fullmatch(
        r"(?:hey\s+jarvis[, ]*)?"
        r"(?:use|from|with|switch\s+(?:back\s+)?to|send\s+(?:from|using))\s+"
        r"(?:my|your|jarvis(?:'s)?)\s+(?:email|gmail|account|mail)"
        r"|switch\s+(?:back\s+)?to\s+jarvis",
        lower,
    ):
        return switched

    if re.search(r"\b(send the email|send email|confirm email|yes send it)\b", lower):
        return gmail_tool.send_pending()
    if re.search(r"\b(cancel email|discard email|cancel the draft|discard draft)\b", lower):
        return gmail_tool.cancel_pending()

    # Unread / inbox
    if re.search(
        r"\b(check|read|show|list|any)\b.{0,20}\b(email|mail|inbox|unread)\b"
        r"|\b(email|mail|inbox|unread)\b.{0,20}\b(check|read|show|list)\b"
        r"|\bunread\s+(mail|email)s?\b"
        r"|\bwhat.?s?\s+(in\s+)?(my\s+)?(inbox|email|mail)\b"
        r"|\bcheck\s+(my\s+)?(gmail|inbox)\b",
        lower,
    ):
        if not gmail_tool.configured():
            return gmail_tool.config_help()
        m = re.search(r"\b(?:last|top|latest)\s+(\d+)\b", lower)
        limit = int(m.group(1)) if m else 5
        result = gmail_tool.list_unread(limit)
        if switched:
            return f"{switched}\n{result}"
        return result

    # Continue multi-step compose
    if gmail_tool.composing():
        if re.search(r"\b(open|launch|volume|mute|search|hunt|remember)\b", lower):
            return None
        continued = gmail_tool.continue_compose(text)
        if continued:
            return continued

    to_only = gmail_tool.parse_recipient_only(text)
    if to_only:
        return gmail_tool.start_compose(to_only)

    # Full compose → ask whose mail (unless already specified in command)
    if re.search(r"\b(email|mail|send\s+(an?\s+)?email)\b", lower) and "@" in text:
        parsed = gmail_tool.parse_compose(text)
        if parsed:
            to, subject, body = parsed
            skip = bool(
                re.search(
                    r"\b(from|using|with)\s+(my|your|jarvis(?:'s)?)\s+(email|mail|gmail)\b"
                    r"|\buse\s+my\s+(email|mail|gmail)\b",
                    lower,
                )
            )
            if skip:
                identity.maybe_switch_from_text(text)
            result = gmail_tool.queue_send(to, subject, body, skip_choice=skip)
            if switched and skip:
                return f"{switched}\n{result}"
            return result
        return (
            "To send mail, say: "
            "email someone@gmail.com subject Hello body Your message here\n"
            "Or just: email someone@gmail.com — I'll ask for subject, body, then whose mail."
        )

    if re.search(r"\bgmail\b", lower) and any(
        w in lower for w in ("setup", "configure", "config", "help", "status")
    ):
        if gmail_tool.configured():
            return (
                f"Mail ready on {identity.account_label()}, sir. "
                "Try 'check my unread email'. Before send I'll ask Jarvis vs your mail."
            )
        return gmail_tool.config_help()

    if switched:
        return switched

    return None
