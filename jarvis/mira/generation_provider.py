"""Future generative-video provider contract for Mira.

Phase 1: interface only. The real generative engine is NOT implemented.
Callers MUST NOT treat this as a working video source.

Existing creative asks still use the legacy stock / Pollinations collage path
in ``pipeline.py``. This module exists so a future provider can plug in without
rewiring live screen-record hard-lock.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class VideoGenerationRequest:
    """Normalized ask for a future generative-video backend."""

    brief: str
    pipeline: str = "creative_generative"  # creative_generative | hybrid
    duration_sec: int = 30
    aspect: str = "9:16"
    voice: str | None = None
    audio_mode: str = "voice"
    search_hints: list[str] = field(default_factory=list)
    live_platform: dict[str, Any] | None = None  # for hybrid: product context
    meta: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class VideoGenerationProvider(Protocol):
    """Contract a real generative-video backend must implement later."""

    provider_id: str

    def is_available(self) -> bool:
        """True when the backend can produce video now."""
        ...

    def generate(self, request: VideoGenerationRequest) -> dict[str, Any]:
        """Produce a video. Must return ok=False until a real backend exists."""
        ...


class UnimplementedGenerationProvider:
    """Explicit non-implementation — never returns fake success or placeholder media."""

    provider_id = "mira_generative_unimplemented"

    def is_available(self) -> bool:
        return False

    def generate(self, request: VideoGenerationRequest) -> dict[str, Any]:
        brief = (request.brief or "").strip()[:120]
        return {
            "ok": False,
            "status": "not_implemented",
            "message": (
                "Mira generative-video provider is not implemented yet "
                f"(Phase 1 routing only). Brief was: {brief or '(empty)'}. "
                "Use the existing stock/AI collage path, or a live product tour."
            )[:320],
            "provider": self.provider_id,
            "pipeline": request.pipeline,
            "notes": ["generation_provider=unimplemented_phase1"],
        }


_DEFAULT: VideoGenerationProvider | None = None


def get_generation_provider() -> VideoGenerationProvider:
    """Return the active generative provider (unimplemented stub until a later phase)."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = UnimplementedGenerationProvider()
    return _DEFAULT


def set_generation_provider(provider: VideoGenerationProvider | None) -> None:
    """Test / future hook to inject a real provider. None resets to unimplemented stub."""
    global _DEFAULT
    _DEFAULT = provider
