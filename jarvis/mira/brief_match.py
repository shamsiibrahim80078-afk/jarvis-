"""Brief compliance — plan/output must match what the user actually asked."""

from __future__ import annotations

import re
from typing import Any

_STOP = frozenset(
    {
        "a", "an", "the", "and", "or", "of", "to", "for", "in", "on", "with", "is",
        "are", "be", "as", "at", "by", "from", "this", "that", "it", "my", "your",
        "make", "create", "generate", "video", "clip", "about", "please", "want",
        "need", "me", "themselves", "themself", "each", "other", "using", "uploads",
        # Instruction / quality words — not visual subjects
        "full", "entire", "complete", "whole", "every", "explore", "deep", "tour",
        "walkthrough", "screen", "record", "recording", "show", "all", "single",
        "thing", "things", "page", "pages", "feature", "features", "smooth",
    }
)

_TALKING = re.compile(
    r"\b(talking|talk|speak|speaking|conversation|conversing|dialogue|dialog|"
    r"chat|chatting|argue|arguing|whisper)\b",
    re.I,
)
_FANTASY = re.compile(
    r"\b(cartoon|fantasy|whimsical|anthropomorphic|magical|fairy|"
    r"superhero|alien|robot|dragon|monster|animated|pixar|disney)\b",
    re.I,
)


def tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {w for w in words if len(w) > 2 and w not in _STOP}


def is_talking_request(text: str) -> bool:
    return bool(_TALKING.search(text or ""))


def wants_cartoon_style(text: str) -> bool:
    return bool(
        re.search(
            r"\b(cartoon|pixar|disney|anime|animated|3d\s+character|anthropomorphic|"
            r"cgi|illustration|drawn)\b",
            text or "",
            re.I,
        )
    )


def needs_fantasy_characters(text: str) -> bool:
    """True when ask needs dialogue between non-human / fantasy subjects."""
    t = text or ""
    subject = re.search(
        r"\b(fruit|fruits|lemon|banana|apple|orange|watermelon|grape|kiwi|pineapple|"
        r"vegetable|vegetables|food|object|objects|toy|toys|"
        r"animal|animals|pet|pets|cat|cats|dog|dogs|car|cars|cloud|clouds|"
        r"star|stars|planet|planets|shoe|shoes|sock|socks|tree|trees|flower|flowers)\b",
        t,
        re.I,
    )
    if is_talking_request(t) and subject:
        return True
    if _FANTASY.search(t) and is_talking_request(t):
        return True
    return bool(_FANTASY.search(t) and re.search(r"\b(character|creature|being)\b", t, re.I))


def plan_match_score(user_brief: str, plan: dict[str, Any]) -> dict[str, Any]:
    """Score whether a director plan covers the user's brief (0–1)."""
    brief_toks = tokenize(user_brief)
    if not brief_toks:
        return {"ok": True, "score": 1.0, "reason": "empty_brief"}

    beats = [b for b in (plan.get("beats") or []) if isinstance(b, dict)]
    blob = " ".join(
        [
            str(plan.get("title") or ""),
            str(plan.get("mood") or ""),
            " ".join(str(b.get("query") or "") for b in beats),
            " ".join(str(b.get("line") or "") for b in beats),
            " ".join(str(b.get("speaker") or "") for b in beats),
            " ".join(str(b.get("still_prompt") or "") for b in beats),
        ]
    ).lower()
    # Synonym-aware hits (dogs ↔ puppy)
    try:
        from jarvis.mira.pexels import _expand_tokens

        blob_toks = tokenize(blob)
        blob_exp = _expand_tokens(blob_toks)
        hit = {t for t in brief_toks if t in blob or t in blob_exp or bool(_expand_tokens({t}) & blob_exp)}
    except Exception:
        hit = {t for t in brief_toks if t in blob}
    score = len(hit) / max(1, len(brief_toks))

    # Single-token briefs: any synonym hit = full match
    if len(brief_toks) == 1 and hit:
        score = max(score, 1.0)

    talking_ok = True
    if is_talking_request(user_brief):
        has_dialogue = any(
            b.get("speaker")
            or re.search(r"\b(i |we |you |hey|hello|said|says)\b", str(b.get("line") or ""), re.I)
            for b in beats
        )
        talking_ok = bool(has_dialogue) or "talk" in blob or "speak" in blob
        if not talking_ok:
            score *= 0.35

    if "office" not in brief_toks and re.search(r"\boffice\b", blob) and score < 0.65:
        score *= 0.35
    # Penalize generic filler stock when the brief has concrete nouns
    if len(brief_toks) >= 2 and score < 0.5:
        score *= 0.85

    ok = score >= 0.62 and talking_ok
    missing = sorted(brief_toks - hit)
    return {
        "ok": ok,
        "score": round(score, 3),
        "matched": sorted(hit),
        "missing": missing[:12],
        "talking_ok": talking_ok,
        "reason": "match" if ok else "brief_mismatch",
    }


def output_match_score(user_brief: str, beats: list[dict[str, Any]]) -> dict[str, Any]:
    """Score assembled beats against the user brief before delivery."""
    fake_plan = {
        "title": " ".join(str(b.get("speaker") or "") for b in beats),
        "beats": beats,
    }
    result = plan_match_score(user_brief, fake_plan)

    # Visual fidelity: VO-only matches are not enough — clips must be on-brief
    visual_ok = 0
    visual_bad = 0
    visual_scores: list[float] = []
    for b in beats:
        if not isinstance(b, dict):
            continue
        # User uploads are trusted as intentional
        if b.get("source") in ("upload", "user") or b.get("kind") == "user":
            visual_ok += 1
            visual_scores.append(1.0)
            continue
        # Real platform screen-records are the exact ask (not stock)
        if b.get("source") == "platform_record" or b.get("kind") == "platform":
            visual_ok += 1
            visual_scores.append(1.0)
            continue
        # Exact-brief stills (AI/Pexels photo of the ask) — trust when line/query is on-brief
        if b.get("kind") == "still" or str(b.get("source") or "").startswith("pollinations"):
            blob = f"{b.get('line') or ''} {b.get('query') or ''}".lower()
            brief_t = tokenize(user_brief)
            if brief_t and all(t in blob for t in brief_t):
                visual_ok += 1
                visual_scores.append(1.0)
                continue
            if brief_t and (brief_t & tokenize(blob)):
                visual_ok += 1
                visual_scores.append(0.9)
                continue
        meta = " ".join(
            [
                str(b.get("visual") or ""),
                str(b.get("pexels_url") or ""),
                str((b.get("relevance") or {}).get("matched") or ""),
            ]
        )
        from jarvis.mira.pexels import visual_relevance

        rel = b.get("relevance") if isinstance(b.get("relevance"), dict) else None
        if not rel:
            rel = visual_relevance(
                user_brief,
                query=str(b.get("query") or ""),
                pexels_url=str(b.get("pexels_url") or meta),
                path=str(b.get("visual") or ""),
            )
        visual_scores.append(float(rel.get("score") or 0))
        if rel.get("ok"):
            visual_ok += 1
        else:
            visual_bad += 1
            # Hard fail office leftovers narrating unrelated topics
            if rel.get("reason") == "office_fallback_reject":
                result["ok"] = False
                result["reason"] = "office_visual_mismatch"
            if rel.get("reason") == "portrait_for_product_reject":
                result["ok"] = False
                result["reason"] = "portrait_product_mismatch"

    if visual_ok + visual_bad > 0:
        v_ratio = visual_ok / max(1, visual_ok + visual_bad)
        result["visual_ok"] = visual_ok
        result["visual_bad"] = visual_bad
        result["visual_ratio"] = round(v_ratio, 3)
        result["visual_score"] = round(sum(visual_scores) / max(1, len(visual_scores)), 3)
        if v_ratio < 0.6:
            result["ok"] = False
            result["reason"] = "visual_mismatch"
            result["score"] = min(float(result.get("score") or 0), 0.35)

    # Exact user uploads: visuals ARE the ask — don't fail on VO token miss.
    # Only when EVERY beat is upload AND VO already carries the brief (or weak brief).
    upload_beats = [
        b
        for b in beats
        if isinstance(b, dict)
        and (b.get("source") in ("upload", "user") or b.get("kind") == "user")
    ]
    if upload_beats and len(upload_beats) == len([b for b in beats if isinstance(b, dict)]):
        vo_blob = " ".join(str(b.get("line") or "") for b in upload_beats).lower()
        brief_toks = tokenize(user_brief)
        vo_hits = {t for t in brief_toks if t in vo_blob} if brief_toks else set()
        vo_ok = (not brief_toks) or (len(vo_hits) / max(1, len(brief_toks)) >= 0.45)
        if vo_ok:
            result["ok"] = True
            result["reason"] = "user_media_exact"
            result["score"] = max(float(result.get("score") or 0), 0.85)
        else:
            # Uploads with off-brief VO = stuck-on-old-idea failure
            result["ok"] = False
            result["reason"] = "upload_vo_mismatch"
            result["score"] = min(float(result.get("score") or 0), 0.3)

    # Real platform screen-tours: visuals ARE the site — don't fail on filler words
    # like "full / every / explore" that never appear in on-screen narration.
    plat_beats = [
        b
        for b in beats
        if isinstance(b, dict)
        and (b.get("source") == "platform_record" or b.get("kind") == "platform")
    ]
    if plat_beats and len(plat_beats) == len([b for b in beats if isinstance(b, dict)]):
        if float(result.get("visual_ratio") or 0) >= 0.9 or visual_ok >= max(2, len(plat_beats) - 1):
            result["ok"] = True
            result["reason"] = "platform_record_exact"
            result["score"] = max(float(result.get("score") or 0), 0.9)
            result["missing"] = []

    if is_talking_request(user_brief):
        char_beats = [
            b
            for b in beats
            if b.get("kind") == "character" or b.get("speaker") or b.get("still_prompt")
        ]
        if len(char_beats) >= 2 and any(b.get("line") for b in char_beats):
            result["talking_ok"] = True
            # Still require visual ratio for stock dialogue path
            if result.get("visual_ratio") is None or float(result.get("visual_ratio") or 0) >= 0.5:
                if float(result.get("score") or 0) >= 0.35 or result.get("matched"):
                    result["score"] = max(float(result.get("score") or 0), 0.55)
                    if result.get("reason") != "visual_mismatch":
                        result["ok"] = True
                        result["reason"] = "character_dialogue"
            else:
                result["ok"] = False
                result["reason"] = "character_off_brief"
    return result
