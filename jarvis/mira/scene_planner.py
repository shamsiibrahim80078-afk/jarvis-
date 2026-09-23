"""Scene planner for Mira creative videos — coherent sequences, not random clips."""

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
    role: str = "beat"  # hook | development | payoff | info | explanation | conclusion

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
    n = max(2, min(10, int(brief.scene_count or 4)))
    if brief.purpose == "explainer":
        base = ["hook", "information", "explanation", "conclusion"]
    elif brief.purpose in ("story", "suspense"):
        base = ["hook", "development", "development", "payoff"]
    elif brief.purpose == "comedy":
        base = ["hook", "setup", "escalation", "punchline"]
    else:
        base = ["hook", "development", "detail", "payoff"]
    while len(base) < n:
        base.insert(-1, "development")
    return base[:n]


def _narration_for(role: str, topic: str, purpose: str, i: int, n: int) -> str:
    t = topic.strip()
    if purpose == "explainer":
        lines = {
            "hook": f"What if we looked closer at {t}?",
            "information": f"Here is the core idea behind {t}.",
            "explanation": f"This is how {t} fits together.",
            "conclusion": f"That is why {t} matters.",
        }
        return lines.get(role, f"Now consider {t}.")
    if purpose == "comedy":
        lines = {
            "hook": f"Nobody warned us about {t}.",
            "setup": f"It starts simple — then {t} gets weird.",
            "escalation": f"And somehow {t} keeps getting worse.",
            "punchline": f"Yes. That was {t}.",
        }
        return lines.get(role, f"{t} — still happening.")
    if purpose in ("story", "suspense"):
        lines = {
            "hook": f"It begins with {t}.",
            "development": f"Something shifts around {t}.",
            "payoff": f"And then the truth about {t} lands.",
        }
        if role == "development" and i > 1:
            return f"The tension around {t} builds."
        return lines.get(role, f"The story of {t} continues.")
    lines = {
        "hook": f"Look — {t}.",
        "development": f"Stay with {t} as the moment unfolds.",
        "detail": f"Every detail of {t} counts.",
        "payoff": f"This is {t}, captured clear and sharp.",
    }
    return lines.get(role, f"{t}.")


def _visual_for(role: str, topic: str, style: str, tone: str) -> tuple[str, str]:
    """Return (visual_prompt, short_search_query)."""
    t = topic.strip()
    style_bit = f"{style} {tone}".strip()
    role_shots = {
        "hook": ("wide establishing shot", f"{t} wide cinematic"),
        "development": ("medium shot, progressing action", f"{t} cinematic"),
        "detail": ("close-up detail", f"{t} close up"),
        "information": ("clear subject focus, readable scene", f"{t} clear"),
        "explanation": ("diagram-like clarity, focused subject", f"{t} detail"),
        "conclusion": ("resolving hero shot", f"{t} cinematic wide"),
        "setup": ("everyday setup shot", f"{t} lifestyle"),
        "escalation": ("dynamic motion, rising energy", f"{t} action"),
        "punchline": ("punchy final frame", f"{t} funny"),
        "payoff": ("satisfying final image", f"{t} cinematic"),
    }
    shot, query = role_shots.get(role, ("cinematic shot", f"{t} cinematic"))
    prompt = (
        f"{t}, {shot}, {style_bit} photography, coherent with previous scenes, "
        f"no watermark, no text overlay"
    )
    return prompt[:400], query[:80]


def plan_scenes(brief: CreativeBrief) -> ScenePlan:
    """Build a coherent scene sequence from a CreativeBrief."""
    roles = _roles_for(brief)
    n = len(roles)
    total = max(8.0, float(brief.duration_sec or 30))
    weights = []
    for r in roles:
        if r in ("hook", "payoff", "punchline", "conclusion"):
            weights.append(1.25)
        elif r in ("explanation", "information"):
            weights.append(1.15)
        else:
            weights.append(1.0)
    wsum = sum(weights) or 1.0
    durs = [max(2.0, total * (w / wsum)) for w in weights]
    drift = total - sum(durs)
    durs[-1] = max(2.0, durs[-1] + drift)

    structure = {
        "explainer": "HOOK → INFORMATION → EXPLANATION → CONCLUSION",
        "story": "HOOK → DEVELOPMENT → PAYOFF",
        "suspense": "HOOK → DEVELOPMENT → PAYOFF",
        "comedy": "HOOK → SETUP → ESCALATION → PUNCHLINE",
    }.get(brief.purpose, "HOOK → DEVELOPMENT → PAYOFF")

    scenes: list[SceneSpec] = []
    for i, role in enumerate(roles):
        vis, query = _visual_for(role, brief.topic, brief.visual_style, brief.tone)
        if brief.search_hints and i < len(brief.search_hints):
            query = brief.search_hints[i][:80]
        narr = ""
        if brief.narration:
            narr = _narration_for(role, brief.topic, brief.purpose, i, n)[:160]
        scenes.append(
            SceneSpec(
                scene_id=f"s{i+1:02d}",
                duration_sec=round(durs[i], 2),
                visual_prompt=vis,
                narration=narr,
                search_query=query,
                transition="cut" if i == 0 else "soft_cut",
                audio_intent="voiceover" if brief.narration else "ambient",
                continuity=brief.continuity,
                role=role,
            )
        )

    title = re.sub(r"\s+", " ", brief.topic)[:48] or "Mira creative"
    return ScenePlan(
        title=title,
        structure=structure,
        scenes=scenes,
        notes=[f"purpose={brief.purpose}", f"scenes={n}", f"duration={brief.duration_sec}"],
    )
