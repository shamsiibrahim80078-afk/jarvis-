"""Mira generative-video provider contract + implementations (Phase 2).

Truth rules:
- Neural / foundation video generation is NOT available in this environment.
- Legacy stock+still collage may run only when explicitly selected, and MUST
  label itself as ``legacy_stock_collage`` — never as neural AI video.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

_OVERRIDE: "VideoGenerationProvider | None" = None


@dataclass
class VideoGenerationRequest:
    """Normalized ask for a creative-video backend."""

    brief: str
    pipeline: str = "creative_generative"
    duration_sec: int = 30
    aspect: str = "9:16"
    voice: str | None = None
    audio_mode: str = "voice"
    search_hints: list[str] = field(default_factory=list)
    live_platform: dict[str, Any] | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class VideoGenerationProvider(Protocol):
    """Contract every creative visual backend must implement."""

    provider_id: str

    def is_available(self) -> bool:
        ...

    def generate(self, request: VideoGenerationRequest) -> dict[str, Any]:
        ...


class UnavailableNeuralVideoProvider:
    """Honest: no Runway/Veo/Sora-class backend is configured in this repo."""

    provider_id = "mira_neural_video_unavailable"

    def is_available(self) -> bool:
        return False

    def generate(self, request: VideoGenerationRequest) -> dict[str, Any]:
        brief = (request.brief or "").strip()[:120]
        return {
            "ok": False,
            "status": "unavailable",
            "message": (
                "No neural video-generation API is configured for Mira "
                "(no Runway/Veo/Sora-class key in .env). "
                f"Brief: {brief or '(empty)'}. "
                "Default mode uses an explicitly labeled legacy stock/still collage "
                "(not AI video). Set MIRA_CREATIVE_VISUAL_MODE=neural_only to force "
                "this unavailable error instead."
            )[:360],
            "provider": self.provider_id,
            "pipeline": request.pipeline,
            "generation_kind": "neural_video",
            "is_neural_video": False,
            "notes": ["generation_provider=neural_unavailable"],
        }


class LegacyStockCollageProvider:
    """Explicit legacy path: Pexels motion / Pollinations stills + Edge TTS.

    This is NOT neural video generation. Results are labeled accordingly.
    """

    provider_id = "mira_legacy_stock_collage"

    def is_available(self) -> bool:
        return True

    def generate(self, request: VideoGenerationRequest) -> dict[str, Any]:
        from jarvis.mira.creative_compose import compose_legacy_collage

        out = compose_legacy_collage(request)
        notes = list(out.get("notes") or [])
        notes.append("generation_kind=legacy_stock_collage")
        notes.append("NOT_neural_ai_video")
        out["notes"] = notes
        out["provider"] = self.provider_id
        out["generation_kind"] = "legacy_stock_collage"
        out["is_neural_video"] = False
        if out.get("ok"):
            msg = out.get("message") or "Video ready."
            if "legacy" not in msg.lower() and "not neural" not in msg.lower():
                out["message"] = (
                    f"{msg} (legacy stock/still collage — not neural AI video)"
                )[:320]
        return out


# Phase 1 test compatibility
UnimplementedGenerationProvider = UnavailableNeuralVideoProvider


def creative_visual_mode() -> str:
    """neural_only | legacy | auto (default)."""
    v = (os.getenv("MIRA_CREATIVE_VISUAL_MODE") or "auto").strip().lower()
    if v in ("neural", "neural_only", "require_neural"):
        return "neural_only"
    if v in ("legacy", "collage", "stock"):
        return "legacy"
    return "auto"


def get_neural_video_provider() -> VideoGenerationProvider:
    return UnavailableNeuralVideoProvider()


def get_generation_provider() -> VideoGenerationProvider:
    """Select creative visual provider — never silently claim neural video."""
    if _OVERRIDE is not None:
        return _OVERRIDE
    mode = creative_visual_mode()
    neural = UnavailableNeuralVideoProvider()
    legacy = LegacyStockCollageProvider()
    if mode == "neural_only":
        return neural
    if mode == "legacy":
        return legacy
    # auto: neural if available, else explicit legacy
    if neural.is_available():
        return neural
    return legacy


def set_generation_provider(provider: VideoGenerationProvider | None) -> None:
    """Test hook — inject a provider. None clears override."""
    global _OVERRIDE
    _OVERRIDE = provider
