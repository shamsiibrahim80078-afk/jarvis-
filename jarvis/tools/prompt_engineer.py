"""Prompt engineer — send a build brief to Cursor (SDK), then email the result.

Usage (chat):
  give cursor a prompt in C:\\Users\\hp\\Desktop\\nexus\\jarvis to build a weather widget
  mail me the last cursor task
  check cursor mail replies
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TASKS_PATH = ROOT / "data" / "cursor_tasks.json"
TASK_TAG = "[JARVIS-CURSOR]"


def _load_tasks() -> list[dict[str, Any]]:
    if not TASKS_PATH.is_file():
        return []
    try:
        data = json.loads(TASKS_PATH.read_text(encoding="utf-8"))
        return list(data) if isinstance(data, list) else []
    except Exception:
        return []


def _save_tasks(tasks: list[dict[str, Any]]) -> None:
    TASKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    TASKS_PATH.write_text(json.dumps(tasks[-40:], indent=2), encoding="utf-8")


def _owner_email() -> str:
    from jarvis import identity

    # Prefer user's personal inbox for "mail me the result"
    return (
        (os.getenv("JARVIS_OWNER_EMAIL") or "").strip()
        or identity.user_mail_address()
        or identity.jarvis_mail_address()
        or ""
    )


def is_prompt_engineer_intent(text: str) -> bool:
    t = (text or "").lower()
    if re.search(r"\b(check|read)\b.{0,20}\bcursor\b.{0,20}\b(mail|email|replies?)\b", t):
        return True
    if re.search(r"\bmail me (the )?(last )?cursor\b", t):
        return True
    if re.search(
        r"\b(give|send|pass)\b.{0,20}\bcursor\b.{0,40}\bprompt\b"
        r"|\bcursor\b.{0,20}\b(prompt|build|implement|fix|refactor)\b"
        r"|\bprompt engineer\b",
        t,
    ):
        return True
    return False


def parse_prompt_command(text: str) -> dict[str, Any] | None:
    """Extract folder + prompt body from natural language."""
    raw = (text or "").strip()
    if not raw:
        return None

    folder = ""
    # Windows / unix path after "in" — stop before " to build|create|…"
    m = re.search(
        r"\bin\s+(?:folder\s+|the\s+folder\s+)?"
        r"[\"']?"
        r"([A-Za-z]:\\(?:[^\"'\n]+?)|/[^\"'\n]+?|\./[^\"'\n]+?|~[/\\][^\"'\n]+?)"
        r"[\"']?"
        r"(?=\s+to\b|\s+saying\b|\s+prompt\b|\s*$|[\"'])",
        raw,
        re.I,
    )
    if m:
        folder = m.group(1).strip().rstrip(".,;")
    if not folder:
        m2 = re.search(r"\bin\s+this\s+(?:folder|repo|project|workspace)\b", raw, re.I)
        if m2:
            folder = str(ROOT)

    # Prompt body: after "to " / "prompt:" / "saying"
    body = ""
    for pat in (
        r"\bprompt\s*[:=]\s*(.+)$",
        r"\bsaying\s*[:=]?\s*(.+)$",
        r"\bto\s+(build|create|implement|fix|refactor|add|make|write)\b(.+)$",
        r"\bgive cursor (?:a )?prompt(?:\s+in\s+[^\s]+)?\s+(?:to\s+)?(.+)$",
    ):
        mm = re.search(pat, raw, re.I | re.S)
        if mm:
            if mm.lastindex and mm.lastindex >= 2:
                body = (mm.group(1) + " " + mm.group(2)).strip()
            else:
                body = mm.group(1).strip()
            break
    if not body:
        # Fallback: strip the lead-in
        body = re.sub(
            r"^.*?\bcursor\b.{0,40}\b(?:prompt|to)\b\s*",
            "",
            raw,
            count=1,
            flags=re.I | re.S,
        ).strip()
    body = re.sub(r"\s+", " ", body).strip(" .")
    if len(body) < 8:
        return None
    return {
        "folder": folder or str(ROOT),
        "prompt": body,
        "mail": bool(re.search(r"\bmail (me|it|result|when)\b", raw, re.I)),
    }


def _run_cursor_sdk(folder: str, prompt: str) -> dict[str, Any]:
    api_key = (os.getenv("CURSOR_API_KEY") or "").strip()
    if not api_key:
        return {
            "ok": False,
            "error": "missing_key",
            "message": (
                "CURSOR_API_KEY is not set in .env, sir. "
                "Add it from https://cursor.com/settings then retry."
            ),
        }
    cwd = Path(folder).expanduser().resolve()
    if not cwd.is_dir():
        return {"ok": False, "error": "bad_folder", "message": f"Folder not found: {cwd}"}

    try:
        from cursor_sdk import Agent, LocalAgentOptions  # type: ignore
    except ImportError:
        try:
            from cursor_sdk import Agent  # type: ignore
            from cursor_sdk import AgentOptions  # type: ignore

            LocalAgentOptions = None  # type: ignore
        except ImportError:
            return {
                "ok": False,
                "error": "sdk_missing",
                "message": (
                    "cursor-sdk is not installed. Run: "
                    "pip install cursor-sdk"
                ),
            }

    model = (os.getenv("CURSOR_AGENT_MODEL") or "composer-2.5").strip()
    text_chunks: list[str] = []
    status = "unknown"
    try:
        opts_kw: dict[str, Any] = {"api_key": api_key, "model": model}
        if LocalAgentOptions is not None:
            opts_kw["local"] = LocalAgentOptions(cwd=str(cwd))
        with Agent.create(**opts_kw) as agent:  # type: ignore[arg-type]
            run = agent.send(prompt)
            for message in run.messages():
                if getattr(message, "type", "") == "assistant":
                    content = getattr(getattr(message, "message", None), "content", None) or []
                    for block in content:
                        if getattr(block, "type", "") == "text":
                            text_chunks.append(str(getattr(block, "text", "") or ""))
            run.wait()
            status = str(getattr(run, "status", None) or getattr(getattr(run, "result", None), "status", "") or "done")
    except TypeError:
        # Older / alternate API: Agent.prompt one-shot
        try:
            from cursor_sdk import Agent, AgentOptions, LocalAgentOptions as LO  # type: ignore

            result = Agent.prompt(
                prompt,
                AgentOptions(api_key=api_key, model=model, local=LO(cwd=str(cwd))),
            )
            status = str(getattr(result, "status", "done"))
            text_chunks.append(str(getattr(result, "result", "") or ""))
        except Exception as exc:
            return {"ok": False, "error": "sdk_fail", "message": f"Cursor SDK failed: {exc}"}
    except Exception as exc:
        return {"ok": False, "error": "sdk_fail", "message": f"Cursor SDK failed: {exc}"}

    full = "\n".join(t for t in text_chunks if t).strip()
    if not full:
        full = "(Cursor finished with no text — check the agent run in Cursor.)"
    return {
        "ok": True,
        "status": status,
        "result": full,
        "folder": str(cwd),
        "prompt": prompt,
    }


def _write_prompt_file(folder: str, prompt: str, task_id: str) -> Path:
    dest_dir = Path(folder).expanduser().resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / f"JARVIS_CURSOR_PROMPT_{task_id}.md"
    path.write_text(
        f"# Jarvis → Cursor brief\n\n"
        f"Task-ID: {task_id}\n"
        f"Created: {datetime.now(timezone.utc).isoformat()}\n\n"
        f"## Prompt\n\n{prompt}\n",
        encoding="utf-8",
    )
    return path


def _email_result(task: dict[str, Any]) -> str:
    to = _owner_email()
    if not to:
        return "No owner email set — add JARVIS_OWNER_EMAIL or your Gmail in .env."
    from jarvis.tools import gmail_tool

    subject = f"{TASK_TAG} {task.get('id')} — Cursor result"
    body = (
        f"Jarvis prompt-engineer report\n"
        f"Task: {task.get('id')}\n"
        f"Folder: {task.get('folder')}\n"
        f"Status: {task.get('status')}\n\n"
        f"=== PROMPT ===\n{task.get('prompt')}\n\n"
        f"=== CURSOR RESULT ===\n{task.get('result')}\n\n"
        f"Reply to this email with more instructions — then tell Jarvis: "
        f"check cursor mail replies\n"
    )
    return gmail_tool.send_email(to, subject, body)


def run_prompt_engineer(text: str) -> str:
    lower = (text or "").lower().strip()

    if re.search(r"\bmail me (the )?(last )?cursor\b", lower):
        tasks = _load_tasks()
        if not tasks:
            return "No Cursor tasks yet, sir."
        last = tasks[-1]
        msg = _email_result(last)
        return f"Emailed last Cursor task {last.get('id')}.\n{msg}"

    if re.search(r"\b(check|read)\b.{0,20}\bcursor\b.{0,20}\b(mail|email|replies?)\b", lower):
        return check_mail_replies()

    parsed = parse_prompt_command(text)
    if not parsed:
        return (
            "Say: give cursor a prompt in <folder> to build … "
            "(and optionally: mail me when done)."
        )

    task_id = uuid.uuid4().hex[:8]
    folder = parsed["folder"]
    prompt = parsed["prompt"]
    want_mail = parsed.get("mail", True)  # default mail when done

    # Always drop a prompt file so you can also paste manually in Cursor
    prompt_file = _write_prompt_file(folder, prompt, task_id)

    sdk = _run_cursor_sdk(folder, prompt)
    task = {
        "id": task_id,
        "created_at": time.time(),
        "folder": folder,
        "prompt": prompt,
        "prompt_file": str(prompt_file),
        "status": "done" if sdk.get("ok") else "error",
        "result": sdk.get("result") or sdk.get("message") or "",
        "error": sdk.get("error"),
    }
    tasks = _load_tasks()
    tasks.append(task)
    _save_tasks(tasks)

    parts = [
        f"Cursor task {task_id} — folder: {folder}",
        f"Prompt file: {prompt_file.name}",
    ]
    if sdk.get("ok"):
        preview = (sdk.get("result") or "")[:400]
        parts.append(f"Cursor finished ({sdk.get('status')}):\n{preview}")
    else:
        parts.append(str(sdk.get("message") or "Cursor run failed."))
        parts.append(
            "I still saved the prompt file — open that folder in Cursor and run the brief, "
            "or set CURSOR_API_KEY for full auto."
        )

    if want_mail or sdk.get("ok"):
        mail_msg = _email_result(task)
        parts.append(mail_msg)

    return "\n".join(parts)


def check_mail_replies() -> str:
    """Look for owner replies tagged with [JARVIS-CURSOR] and queue follow-ups."""
    from jarvis.tools import gmail_tool

    if not gmail_tool.configured():
        return gmail_tool.config_help()
    unread = gmail_tool.list_unread(8)
    if "login failed" in unread.lower() or "app password" in unread.lower():
        return unread
    # Soft parse: if a reply mentions a task id, record it for next Cursor run
    tasks = _load_tasks()
    found: list[str] = []
    for task in reversed(tasks[-10:]):
        tid = str(task.get("id") or "")
        if tid and tid in unread:
            found.append(tid)
            task["mail_reply_seen"] = True
            task["mail_reply_snippet"] = unread[:500]
    if found:
        _save_tasks(tasks)
        return (
            f"Found mail about Cursor task(s): {', '.join(found)}. "
            f"Say: give cursor a prompt … with your reply instructions, "
            f"or paste the reply body and I'll forward it to Cursor."
        )
    return (
        f"No tagged Cursor replies spotted in unread yet.\n{unread[:400]}"
    )


def handle(text: str) -> str | None:
    if not is_prompt_engineer_intent(text):
        return None
    return run_prompt_engineer(text)
