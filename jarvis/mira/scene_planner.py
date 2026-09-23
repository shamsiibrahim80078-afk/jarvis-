"""Scene planner for Mira creative videos — coherent story sequences.

Phase 5A: story beats + prompt-level continuity.
Phase 5C-1: hook contract, pacing from brief.pacing, shot variety,
user-script preservation (templates fill gaps only).

Prompt-level continuity only: each scene carries text context from the previous
scene. This does NOT provide true visual/character locking across generations.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from jarvis.mira.creative_brief import CreativeBrief


@dataclass
class SceneSpec:
    scene_id: str
    duration_sec: float
    visual_prompt: str
    narration: str
    search_query: str
    transition: str = "cut"
    audio_intent: str = "voiceover"
    continuity: str = ""
    role: str = "beat"  # story beat: hook | setup | development | turn | payoff | …
    story_beat: str = ""
    previous_scene_summary: str = ""
    continuity_bridge: str = ""
    progress_note: str = ""
    # Phase 5C-1: deterministic shot variety line (framing / move / action / env)
    shot_plan: str = ""
    hook_intent: str = ""  # set on scene 1 only
    narration_source: str = ""  # "user_script" | "template" | ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScenePlan:
    title: str
    structure: str
    scenes: list[SceneSpec] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "structure": self.structure,
            "scenes": [s.to_dict() for s in self.scenes],
            "notes": list(self.notes),
        }


def _roles_for(brief: CreativeBrief) -> list[str]:
    """Assign story beats adapted to requested scene count (not one fixed story)."""
    n = max(2, min(10, int(brief.scene_count or 4)))
    purpose = brief.purpose

    if purpose == "explainer":
        # pedagogical arc
        if n == 2:
            return ["hook", "conclusion"]
        if n == 3:
            return ["hook", "explanation", "conclusion"]
        if n == 4:
            return ["hook", "information", "explanation", "conclusion"]
        beats = ["hook", "information"]
        mid = n - 3  # leave room for explanation + conclusion
        for i in range(max(1, mid)):
            beats.append("explanation" if i == mid - 1 else "development")
        beats.append("conclusion")
        return beats[:n]

    if purpose == "comedy":
        if n == 2:
            return ["hook", "punchline"]
        if n == 3:
            return ["hook", "setup", "punchline"]
        if n == 4:
            return ["hook", "setup", "escalation", "punchline"]
        beats = ["hook", "setup"]
        for _ in range(n - 4):
            beats.append("escalation")
        beats.extend(["escalation", "punchline"])
        return beats[:n]

    # story / suspense / promo / lifestyle / general — dramatic arc
    if n == 2:
        return ["hook", "payoff"]
    if n == 3:
        return ["hook", "development", "payoff"]
    if n == 4:
        return ["hook", "setup", "turn", "payoff"]
    if n == 5:
        return ["hook", "setup", "development", "turn", "payoff"]
    # n >= 6: hook → setup → developments → turn → payoff
    beats = ["hook", "setup"]
    mid_count = n - 4  # development slots before turn
    for i in range(max(1, mid_count)):
        if i == mid_count - 1 and mid_count > 1:
            beats.append("escalation")
        else:
            beats.append("development")
    beats.extend(["turn", "payoff"])
    return beats[:n]


def _structure_label(purpose: str, roles: list[str]) -> str:
    return " → ".join(r.upper() for r in roles)


def _short_topic(topic: str, limit: int = 48) -> str:
    t = (topic or "").strip()
    if len(t) <= limit:
        return t
    return (t[: limit - 3].rsplit(" ", 1)[0] or t[: limit - 3]).strip() or t[:limit]


def _hook_intent_for(purpose: str) -> str:
    """Purpose-aware hook job — no forced suspense on explainers/promos."""
    return {
        "explainer": "curiosity — open a clear question about the subject",
        "comedy": "pattern break — odd or unexpected first beat on the subject",
        "suspense": "stakes — withhold the full picture; tension around the subject",
        "story": "in-media-res — open mid-moment with stakes on the subject",
        "promo": "promise — show why the subject is worth watching now",
        "lifestyle": "invite — drop into the subject's world immediately",
        "general": "curiosity — make the subject ask a silent question",
    }.get(purpose, "curiosity — make the subject ask a silent question")


def _hook_shot_parts(purpose: str) -> tuple[str, str, str, str]:
    """Distinct hook framing/move/action/env — not a generic wide establish."""
    # framing, camera movement, subject/action, environment/context
    if purpose == "explainer":
        return (
            "tight curiosity insert",
            "slow push-in",
            "subject detail that raises a question",
            "readable primary setting",
        )
    if purpose == "comedy":
        return (
            "unexpected close cutaway",
            "snap energy hold",
            "subject doing something slightly wrong",
            "ordinary space about to break",
        )
    if purpose == "suspense":
        return (
            "partial reveal frame",
            "creeping push-in",
            "subject half-seen / withheld",
            "edge of the threatened space",
        )
    if purpose == "story":
        return (
            "in-media-res medium",
            "locked-off then drift",
            "subject already in motion with stakes",
            "story world mid-action",
        )
    if purpose == "promo":
        return (
            "striking hero detail",
            "confident push-in",
            "subject at its best first second",
            "clean showcase space",
        )
    if purpose == "lifestyle":
        return (
            "intimate over-shoulder",
            "gentle handheld drift",
            "subject mid-routine",
            "lived-in pocket of the space",
        )
    # general
    return (
        "striking subject detail",
        "slow push-in",
        "subject framed to raise a question",
        "primary setting, first glance",
    )


def _beat_change(role: str, i: int, n: int, *, purpose: str = "general") -> str:
    """What advances in this beat relative to the previous one."""
    if role == "hook" or i == 0:
        return _hook_intent_for(purpose)
    changes = {
        "setup": "introduce the situation and ordinary rhythm before change",
        "development": "advance the action; deepen the same subject and place",
        "information": "reveal a clear fact about the subject",
        "explanation": "show how the pieces connect",
        "escalation": "raise energy, stakes, or absurdity",
        "turn": "a decisive shift — something new happens to the same subject",
        "detail": "push in closer on a meaningful detail of the same subject",
        "punchline": "land the comic beat while keeping the same world",
        "payoff": "resolve the arc; final clear image of the same subject",
        "conclusion": "close with a crisp takeaway image",
    }
    base = changes.get(role, "continue the same story forward")
    if i == n - 1:
        return f"{base}; close the sequence"
    return f"{base} (beat {i + 1} of {n})"


def _hook_narration(topic: str, purpose: str) -> str:
    """Topic-specific hook VO — no invented facts; purpose-aware tone."""
    short = _short_topic(topic)
    if purpose == "explainer":
        return f"What makes {short} worth a closer look?"
    if purpose == "comedy":
        return f"Nobody warned you about {short}."
    if purpose == "suspense":
        return f"Something feels off about {short}."
    if purpose == "story":
        return f"It begins with {short} — and it will not stay still."
    if purpose == "promo":
        return f"Watch what {short} can do in seconds."
    if purpose == "lifestyle":
        return f"Drop into {short} from the first frame."
    return f"Stay with {short} from the first second."


def _narration_for(
    role: str,
    topic: str,
    purpose: str,
    i: int,
    n: int,
    *,
    prev_role: str = "",
) -> str:
    """Sequence-aware VO — each beat advances; not a repeated topic chant."""
    if role == "hook" or i == 0:
        return _hook_narration(topic, purpose)[:160]

    short = _short_topic(topic)

    if purpose == "explainer":
        seq = [
            f"What makes {short} worth a closer look?",  # unused when hook handled
            f"The key idea is how {short} actually works.",
            f"Watch the pieces of {short} lock into place.",
            f"That connection is why {short} matters.",
            f"One more layer: {short} in everyday terms.",
            f"Pull back — {short} as a clear whole.",
            f"Remember this about {short}.",
            f"That is the takeaway on {short}.",
        ]
    elif purpose == "comedy":
        seq = [
            f"Nobody warned you about {short}.",
            f"Then {short} took a left turn.",
            f"Somehow {short} got louder.",
            f"And yes — that is exactly {short}.",
            f"{short} refuses to behave.",
            f"Cut to: {short}, still escalating.",
            f"Final beat: {short} wins the bit.",
            f"Credits would just say {short}.",
        ]
    elif purpose in ("story", "suspense"):
        seq = [
            f"It begins with {short} — and it will not stay still.",
            f"At first, {short} seems quiet enough.",
            f"Something in {short} starts to shift.",
            f"The turn hits — {short} is not what it was.",
            f"Pressure builds around {short}.",
            f"There is no going back from {short}.",
            f"Everything leans into {short}.",
            f"It ends on {short}, changed.",
        ]
    else:
        seq = [
            f"Stay with {short} from the first second.",
            f"Stay with {short} as the frame settles.",
            f"Now {short} moves forward.",
            f"A turn: {short} from a new angle.",
            f"Details of {short} come into focus.",
            f"Energy rises around {short}.",
            f"Hold on {short} as it lands.",
            f"Close on {short}, clear and final.",
        ]

    if i < len(seq):
        line = seq[i]
    else:
        line = f"Next, {short} continues — moment {i + 1} of {n}."

    if role == "turn" and "turn" not in line.lower():
        line = f"Then the turn: {line[0].lower() + line[1:]}" if len(line) > 1 else line
    if prev_role and i > 0 and role == "payoff":
        line = f"Finally — {line[0].lower() + line[1:]}" if len(line) > 1 else line

    return line[:160]


# --- Shot variety (deterministic, adjacent-distinct) ---

_FRAMINGS = (
    "wide frame",
    "medium frame",
    "close-up",
    "over-shoulder",
    "low-angle",
    "high-angle",
    "detail insert",
    "profile medium",
)
_MOVEMENTS = (
    "locked-off",
    "slow push-in",
    "gentle drift",
    "lateral track",
    "static hold",
    "orbiting arc",
    "pull-back",
    "snap cut energy",
)
_ACTIONS = (
    "subject enters frame",
    "subject acts in place",
    "environment reacts around subject",
    "meaningful detail reveals",
    "subject turns / redirects",
    "moment settles on subject",
    "subject interacts with space",
    "stakes rise on subject",
)
_ENVIRONMENTS = (
    "primary setting center",
    "edge of the same space",
    "closer pocket of the same world",
    "atmospheric backdrop of the setting",
    "grounded foreground of the place",
    "lit corner of the same environment",
    "open span of the same location",
    "intimate zone within the scene",
)


def _purpose_offset(purpose: str) -> int:
    return {
        "explainer": 1,
        "comedy": 2,
        "suspense": 3,
        "story": 4,
        "promo": 5,
        "lifestyle": 6,
        "general": 0,
    }.get(purpose, 0)


def _format_shot_plan(
    framing: str, movement: str, action: str, environment: str
) -> str:
    return f"{framing}; {movement}; {action}; {environment}"


def _shot_signature(plan: str) -> tuple[str, str]:
    """Compare adjacent variety on framing + movement primarily."""
    parts = [p.strip() for p in (plan or "").split(";")]
    framing = parts[0] if parts else ""
    movement = parts[1] if len(parts) > 1 else ""
    return framing.lower(), movement.lower()


def build_shot_variety_plans(
    roles: list[str],
    purpose: str,
    topic: str,
) -> list[str]:
    """Deterministic shot plans — vary framing/move/action/env; no adjacent repeats."""
    n = len(roles)
    off = _purpose_offset(purpose)
    plans: list[str] = []
    prev_sig: tuple[str, str] | None = None

    for i, role in enumerate(roles):
        if role == "hook" or i == 0:
            framing, movement, action, environment = _hook_shot_parts(purpose)
        else:
            fi = (i * 3 + off) % len(_FRAMINGS)
            mi = (i * 5 + off + 1) % len(_MOVEMENTS)
            ai = (i * 2 + off + 2) % len(_ACTIONS)
            ei = (i * 4 + off) % len(_ENVIRONMENTS)
            # Role nudges for turn/payoff clarity
            if role in ("turn", "escalation"):
                fi = (fi + 2) % len(_FRAMINGS)
                mi = (mi + 1) % len(_MOVEMENTS)
            if role in ("payoff", "punchline", "conclusion"):
                ai = (ai + 3) % len(_ACTIONS)
                ei = (ei + 1) % len(_ENVIRONMENTS)
            if role in ("information", "explanation"):
                fi = _FRAMINGS.index("medium frame")
            framing = _FRAMINGS[fi]
            movement = _MOVEMENTS[mi]
            action = _ACTIONS[ai]
            environment = _ENVIRONMENTS[ei]

        plan = _format_shot_plan(framing, movement, action, environment)
        sig = _shot_signature(plan)
        # Shift until adjacent framing+movement differs
        shift = 0
        while prev_sig is not None and sig == prev_sig and shift < 8:
            shift += 1
            if role == "hook" or i == 0:
                # Keep hook intent; only nudge movement/env
                movement = _MOVEMENTS[(off + shift + 3) % len(_MOVEMENTS)]
                environment = _ENVIRONMENTS[(off + shift) % len(_ENVIRONMENTS)]
            else:
                framing = _FRAMINGS[(fi + shift) % len(_FRAMINGS)]
                movement = _MOVEMENTS[(mi + shift + 1) % len(_MOVEMENTS)]
            plan = _format_shot_plan(framing, movement, action, environment)
            sig = _shot_signature(plan)

        plans.append(plan)
        prev_sig = sig

    # Topic appears only in visual prompt / search — keep plans camera-language only
    _ = topic  # reserved for future topic-tied action nouns without inventing facts
    assert len(plans) == n
    return plans


def _search_query_for(topic: str, shot_plan: str, role: str) -> str:
    t = topic.strip()
    framing = (shot_plan.split(";")[0] if shot_plan else role).strip()
    # Short search-friendly query for stock fallback
    return f"{t} {framing}"[:80]


def _visual_for(
    role: str,
    topic: str,
    style: str,
    tone: str,
    *,
    continuity: str,
    previous_summary: str,
    progress_note: str,
    scene_index: int,
    shot_plan: str,
    hook_intent: str = "",
) -> tuple[str, str]:
    """Return (visual_prompt, short_search_query) with prompt-level continuity."""
    t = topic.strip()
    style_bit = f"{style} {tone}".strip()
    shot = shot_plan or "cinematic shot"
    query = _search_query_for(t, shot, role)

    if scene_index == 0:
        intent_bit = hook_intent or progress_note
        prompt = (
            f"{t}, HOOK shot: {shot}, {style_bit} look. "
            f"Hook intent: {intent_bit}. "
            f"Establish subject identity and setting for a continuous story. "
            f"{continuity} "
            f"Prompt-level continuity only (not a locked character reference). "
            f"no watermark, no text overlay"
        )
    else:
        prev = (previous_summary or "")[:100]
        prompt = (
            f"CONTINUATION of the same story about {t}. "
            f"Previous scene: {prev}. "
            f"Keep the same subject identity, setting family, lighting family, and {style_bit} style. "
            f"Prompt-level continuity only — do not invent a new character or world. "
            f"What changes now ({role}): {progress_note}. "
            f"Shot variety: {shot}. {continuity} "
            f"no watermark, no text overlay"
        )
    return prompt[:520], query[:80]


def _scene_summary(role: str, topic: str, progress_note: str) -> str:
    t = topic.strip()[:80]
    return f"{role} on '{t}': {progress_note}"[:160]


def _normalize_pacing(pacing: str) -> str:
    p = (pacing or "medium").strip().lower()
    if p not in ("fast", "medium", "clear"):
        return "medium"
    return p


def duration_weights_for(roles: list[str], pacing: str) -> list[float]:
    """Role × pacing weights (Phase 5C-1). Public for tests."""
    p = _normalize_pacing(pacing)
    n = len(roles)
    weights: list[float] = []
    for i, r in enumerate(roles):
        if r == "hook" or i == 0:
            w = 1.2
        elif r in ("payoff", "punchline", "conclusion"):
            w = 1.2
        elif r == "turn":
            w = 1.15
        elif r in ("explanation", "information", "setup"):
            w = 1.1
        elif r == "escalation":
            w = 1.05
        else:
            w = 1.0

        if p == "fast":
            if r == "hook" or i == 0:
                w *= 1.35
            elif r in ("development", "information", "setup") and 0 < i < n - 1:
                w *= 0.78
            elif r == "escalation" and 0 < i < n - 1:
                w *= 0.85
            elif r in ("payoff", "punchline", "conclusion"):
                w *= 1.05
        elif p == "clear":
            if r in ("setup", "information", "explanation"):
                w *= 1.3
            elif r in ("payoff", "punchline", "conclusion"):
                w *= 1.25
            elif r == "hook" or i == 0:
                w *= 1.05
            elif r == "development":
                w *= 1.1
        # medium: role base only
        weights.append(w)
    return weights


def _durations_for(roles: list[str], total: float, pacing: str) -> list[float]:
    """Allocate scene durations from pacing weights; keep Phase 5B-safe bounds."""
    total = max(8.0, float(total))
    weights = duration_weights_for(roles, pacing)
    wsum = sum(weights) or 1.0
    # Cap any single scene so VO/encode stay sane (compose also clamps 1.5–28)
    max_one = min(28.0, max(4.0, total * 0.55))
    durs = [max(2.0, min(max_one, total * (w / wsum))) for w in weights]
    # Renormalize to total
    s = sum(durs) or 1.0
    durs = [max(2.0, d * (total / s)) for d in durs]
    drift = total - sum(durs)
    durs[-1] = max(2.0, min(max_one, durs[-1] + drift))
    return durs


def plan_scenes(brief: CreativeBrief) -> ScenePlan:
    """Build a coherent story scene sequence from a CreativeBrief."""
    roles = _roles_for(brief)
    n = len(roles)
    total = max(8.0, float(brief.duration_sec or 30))
    pacing = _normalize_pacing(brief.pacing)
    durs = _durations_for(roles, total, pacing)

    structure = _structure_label(brief.purpose, roles)
    continuity = (brief.continuity or "").strip() or (
        f"Keep visual continuity on: {brief.topic}. Same world, lighting family, and subject identity."
    )

    shot_plans = build_shot_variety_plans(roles, brief.purpose, brief.topic)
    user_lines = [
        str(s).strip()[:160]
        for s in (brief.script_lines or brief.extras.get("script_lines") or [])
        if str(s).strip()
    ]

    scenes: list[SceneSpec] = []
    prev_summary = ""
    prev_role = ""
    for i, role in enumerate(roles):
        progress = _beat_change(role, i, n, purpose=brief.purpose)
        hook_intent = _hook_intent_for(brief.purpose) if (role == "hook" or i == 0) else ""
        shot = shot_plans[i]
        vis, query = _visual_for(
            role,
            brief.topic,
            brief.visual_style,
            brief.tone,
            continuity=continuity,
            previous_summary=prev_summary or "(opening)",
            progress_note=progress,
            scene_index=i,
            shot_plan=shot,
            hook_intent=hook_intent,
        )
        if brief.search_hints and i < len(brief.search_hints):
            query = brief.search_hints[i][:80]

        narr = ""
        narr_src = ""
        if brief.narration:
            if i < len(user_lines) and user_lines[i]:
                narr = user_lines[i][:160]
                narr_src = "user_script"
            else:
                narr = _narration_for(
                    role, brief.topic, brief.purpose, i, n, prev_role=prev_role
                )[:160]
                narr_src = "template"

        bridge = (
            f"HOOK — {hook_intent}"
            if i == 0
            else f"Continue from [{prev_role}] → [{role}]: {progress}"
        )
        summary = _scene_summary(role, brief.topic, progress)
        scenes.append(
            SceneSpec(
                scene_id=f"s{i+1:02d}",
                duration_sec=round(durs[i], 2),
                visual_prompt=vis,
                narration=narr,
                search_query=query,
                transition="cut" if i == 0 else "soft_cut",
                audio_intent="voiceover" if brief.narration else "ambient",
                continuity=continuity,
                role=role,
                story_beat=role,
                previous_scene_summary=prev_summary,
                continuity_bridge=bridge,
                progress_note=progress,
                shot_plan=shot,
                hook_intent=hook_intent,
                narration_source=narr_src,
            )
        )
        prev_summary = summary
        prev_role = role

    title = re.sub(r"\s+", " ", brief.topic)[:48] or "Mira creative"
    notes = [
        f"purpose={brief.purpose}",
        f"scenes={n}",
        f"duration={brief.duration_sec}",
        f"pacing={pacing}",
        "continuity=prompt_level_only",
        "phase=5a_story_foundation",
        "phase=5c1_watchability",
        "hook=contract",
        "shot_variety=deterministic",
    ]
    if user_lines:
        notes.append(f"user_script_lines={len(user_lines)}")
        notes.append("narration=user_script_preferred")
    return ScenePlan(
        title=title,
        structure=structure,
        scenes=scenes,
        notes=notes,
    )
