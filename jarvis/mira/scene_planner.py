"""Scene planner for Mira creative videos — coherent story sequences (Phase 5A).

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


def _beat_change(role: str, i: int, n: int) -> str:
    """What advances in this beat relative to the previous one."""
    changes = {
        "hook": "open on the subject; establish world and stakes",
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
    if i == 0:
        return base
    if i == n - 1:
        return f"{base}; close the sequence"
    return f"{base} (beat {i + 1} of {n})"


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
    t = topic.strip()
    # Short topic noun phrase for readability
    short = t if len(t) <= 48 else (t[:45].rsplit(" ", 1)[0] or t[:45])

    if purpose == "explainer":
        seq = [
            f"Start here: what makes {short} worth a closer look.",
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
            f"It looked normal… until {short}.",
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
            f"It opens on {short}.",
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
            f"Look first at {short}.",
            f"Stay with {short} as the frame settles.",
            f"Now {short} moves forward.",
            f"A turn: {short} from a new angle.",
            f"Details of {short} come into focus.",
            f"Energy rises around {short}.",
            f"Hold on {short} as it lands.",
            f"Close on {short}, clear and final.",
        ]

    # Map beat index into a unique line; avoid reusing same string
    if i < len(seq):
        line = seq[i]
    else:
        line = f"Next, {short} continues — moment {i + 1} of {n}."

    # Soft beat flavor without collapsing uniqueness
    if role == "turn" and "turn" not in line.lower():
        line = f"Then the turn: {line[0].lower() + line[1:]}" if len(line) > 1 else line
    if prev_role and i > 0 and role == "payoff":
        line = f"Finally — {line[0].lower() + line[1:]}" if len(line) > 1 else line

    return line[:160]


def _shot_for(role: str, topic: str) -> tuple[str, str]:
    t = topic.strip()
    role_shots = {
        "hook": ("wide establishing shot", f"{t} wide cinematic"),
        "setup": ("medium establishing action", f"{t} setup cinematic"),
        "development": ("medium shot, progressing action", f"{t} cinematic"),
        "escalation": ("dynamic motion, rising energy", f"{t} action"),
        "turn": ("decisive angle change, same subject", f"{t} dramatic"),
        "detail": ("close-up detail", f"{t} close up"),
        "information": ("clear subject focus, readable scene", f"{t} clear"),
        "explanation": ("diagram-like clarity, focused subject", f"{t} detail"),
        "conclusion": ("resolving hero shot", f"{t} cinematic wide"),
        "punchline": ("punchy final frame", f"{t} funny"),
        "payoff": ("satisfying final image", f"{t} cinematic"),
    }
    return role_shots.get(role, ("cinematic shot", f"{t} cinematic"))


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
) -> tuple[str, str]:
    """Return (visual_prompt, short_search_query) with explicit prompt-level continuity."""
    t = topic.strip()
    style_bit = f"{style} {tone}".strip()
    shot, query = _shot_for(role, t)

    if scene_index == 0:
        prompt = (
            f"{t}, {shot}, {style_bit} look. "
            f"Establish subject identity and setting for a continuous story. "
            f"{continuity} "
            f"Progress: {progress_note}. "
            f"Prompt-level continuity only (not a locked character reference). "
            f"no watermark, no text overlay"
        )
    else:
        prompt = (
            f"CONTINUATION of the same story about {t}. "
            f"Previous scene: {previous_summary}. "
            f"Keep the same subject identity, setting family, lighting family, and {style_bit} style. "
            f"What changes now ({role}): {progress_note}. "
            f"Visual: {shot}. {continuity} "
            f"Prompt-level continuity only — do not invent a new character or world. "
            f"no watermark, no text overlay"
        )
    return prompt[:480], query[:80]


def _scene_summary(role: str, topic: str, progress_note: str) -> str:
    t = topic.strip()[:80]
    return f"{role} on '{t}': {progress_note}"[:160]


def plan_scenes(brief: CreativeBrief) -> ScenePlan:
    """Build a coherent story scene sequence from a CreativeBrief."""
    roles = _roles_for(brief)
    n = len(roles)
    total = max(8.0, float(brief.duration_sec or 30))
    weights = []
    for r in roles:
        if r in ("hook", "payoff", "punchline", "conclusion", "turn"):
            weights.append(1.25)
        elif r in ("explanation", "information", "escalation"):
            weights.append(1.15)
        else:
            weights.append(1.0)
    wsum = sum(weights) or 1.0
    durs = [max(2.0, total * (w / wsum)) for w in weights]
    drift = total - sum(durs)
    durs[-1] = max(2.0, durs[-1] + drift)

    structure = _structure_label(brief.purpose, roles)
    continuity = (brief.continuity or "").strip() or (
        f"Keep visual continuity on: {brief.topic}. Same world, lighting family, and subject identity."
    )

    scenes: list[SceneSpec] = []
    prev_summary = ""
    prev_role = ""
    for i, role in enumerate(roles):
        progress = _beat_change(role, i, n)
        vis, query = _visual_for(
            role,
            brief.topic,
            brief.visual_style,
            brief.tone,
            continuity=continuity,
            previous_summary=prev_summary or "(opening)",
            progress_note=progress,
            scene_index=i,
        )
        if brief.search_hints and i < len(brief.search_hints):
            query = brief.search_hints[i][:80]
        narr = ""
        if brief.narration:
            narr = _narration_for(
                role, brief.topic, brief.purpose, i, n, prev_role=prev_role
            )[:160]
        bridge = (
            "Opening beat — establish subject and world."
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
            )
        )
        prev_summary = summary
        prev_role = role

    title = re.sub(r"\s+", " ", brief.topic)[:48] or "Mira creative"
    return ScenePlan(
        title=title,
        structure=structure,
        scenes=scenes,
        notes=[
            f"purpose={brief.purpose}",
            f"scenes={n}",
            f"duration={brief.duration_sec}",
            "continuity=prompt_level_only",
            "phase=5a_story_foundation",
        ],
    )
