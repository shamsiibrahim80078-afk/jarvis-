"""Mira agent loop — plan → make → verify → fix until brief matches (or give up).

This is the quality gate that stops random/off-brief delivery.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable

logger = logging.getLogger(__name__)


def _tighten_hints(topic: str, missing: list[str] | None, attempt: int) -> list[str]:
    """Build stricter Pexels queries from topic + missing tokens."""
    from jarvis.mira.pexels import _pexels_query_variants

    base = _pexels_query_variants(topic) or [topic]
    miss = [m for m in (missing or []) if m and len(m) > 2][:4]
    out: list[str] = []
    if miss:
        out.append(" ".join(miss)[:80])
        out.append(f"{miss[0]} {' '.join(miss[1:3])}".strip()[:80])
    for b in base:
        out.append(b)
        if miss:
            out.append(f"{b} {miss[0]}"[:80])
    # Attempt 2+: shorter core nouns only
    if attempt >= 1:
        nouns = [w for w in re.findall(r"[a-zA-Z]+", topic.lower()) if len(w) > 3][:3]
        if nouns:
            out.insert(0, " ".join(nouns))
            out.insert(1, nouns[0])
    # Dedupe
    seen: set[str] = set()
    uniq: list[str] = []
    for q in out:
        k = q.lower().strip()
        if k and k not in seen:
            seen.add(k)
            uniq.append(q.strip())
    return uniq[:6]


def verify_result(brief: str, result: dict[str, Any]) -> dict[str, Any]:
    """Score whether a finished Mira result matches the user brief."""
    from jarvis.mira.brief_match import output_match_score

    if not result or not result.get("ok"):
        return {
            "ok": False,
            "score": 0.0,
            "reason": "generate_failed",
            "missing": [],
            "message": result.get("message") if isinstance(result, dict) else "failed",
        }
    beats = list(result.get("beats") or [])
    # Always recompute against the CLEAN user brief (ignore polluted internal scores)
    m = output_match_score(brief, beats)

    path = result.get("video_path") or result.get("image_path") or ""
    if path:
        from pathlib import Path

        if not Path(str(path)).is_file():
            m["ok"] = False
            m["reason"] = "missing_file"

    if result.get("video_path") and len(beats) < 2 and result.get("provider") != "mira_edit":
        # Live platform / product tours can be 1 strong scene (quick teaser) — do not fail them
        prov = str(result.get("provider") or "")
        if prov in (
            "mira_platform_screen_record",
            "mira_platform_required",
        ) or str(result.get("still_source") or "") in ("platform_record", "platform_screen"):
            pass
        elif "edit_" not in str(path):
            m["ok"] = False
            m["reason"] = m.get("reason") or "too_few_beats"

    return m


def run_with_verify(
    brief: str,
    make_fn: Callable[..., dict[str, Any]],
    *,
    max_attempts: int = 3,
    make_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Call make_fn up to max_attempts. After each attempt, verify against brief.
    On failure, tighten search_hints / script and retry.
    Only returns ok=True when verify passes.
    """
    kwargs = dict(make_kwargs or {})
    notes: list[str] = ["agent_loop=verify_fix"]
    last: dict[str, Any] = {"ok": False, "message": "no attempt"}
    last_match: dict[str, Any] = {"ok": False}

    for attempt in range(max(1, min(5, int(max_attempts or 3)))):
        notes.append(f"attempt={attempt + 1}")
        try:
            last = make_fn(**kwargs)
        except Exception as exc:
            last = {"ok": False, "message": str(exc)[:240], "notes": []}
            notes.append(f"exception:{exc}")
            continue

        match = verify_result(brief, last)
        last_match = match
        last["brief_match"] = match
        notes.append(f"verify={match}")

        if last.get("ok") and match.get("ok"):
            merged_notes = list(last.get("notes") or []) + notes
            last["notes"] = merged_notes
            last["agent_verified"] = True
            last["agent_attempts"] = attempt + 1
            msg = last.get("message") or "Ready."
            last["message"] = f"{msg} (verified OK · attempt {attempt + 1})"
            return last

        # Fix plan for next attempt — tighten SEARCH only (never pollute VO script)
        missing = list(match.get("missing") or [])
        hints = _tighten_hints(brief, missing, attempt)
        kwargs["search_hints"] = hints
        # Keep original creative brief as script
        kwargs["script"] = brief
        # Never "fix" a hard-locked platform fail by inventing stock / portraits
        last_notes = " ".join(str(n) for n in (last.get("notes") or []))
        last_prov = str(last.get("provider") or "")
        if (
            "platform_hard_lock" in last_notes
            or last_prov in ("mira_platform_required", "mira_platform_screen_record")
        ):
            fail_notes = list(last.get("notes") or []) + notes + ["agent_no_stock_after_platform"]
            return {
                "ok": False,
                "status": "error",
                "message": (
                    last.get("message")
                    or "Live product tour failed — will not invent random stock scenes."
                )[:320],
                "notes": fail_notes,
                "brief_match": last_match,
                "last_attempt": last,
                "agent_verified": False,
                "agent_attempts": attempt + 1,
            }
        # If uploads path failed fidelity, fall back to stock for retries
        reason = str(match.get("reason") or "")
        if kwargs.get("use_uploads") and reason in (
            "visual_mismatch",
            "office_visual_mismatch",
            "brief_mismatch",
            "portrait_product_mismatch",
        ):
            kwargs["use_uploads"] = False
            kwargs.pop("media_paths", None)
            notes.append("retry_drop_uploads")
        notes.append(f"retry_hints={hints[:3]}")

    # Exhausted — do not deliver random/off-brief as success
    fail_notes = list(last.get("notes") or []) + notes
    return {
        "ok": False,
        "status": "error",
        "message": (
            f"Could not match your ask after {max_attempts} tries "
            f"(score={last_match.get('score')}, missing={', '.join(last_match.get('missing') or [])}). "
            "Try a clearer topic."
        )[:320],
        "notes": fail_notes,
        "brief_match": last_match,
        "last_attempt": last,
        "agent_verified": False,
        "agent_attempts": max_attempts,
    }
