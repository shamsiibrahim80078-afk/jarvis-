"""Hugging Face Inference Providers — remote text-to-video for Mira.

Uses ``huggingface_hub.InferenceClient.text_to_video`` when available.
Requires ``HF_TOKEN`` with Inference Providers permission.

This is NOT local CUDA inference. Credits/billing follow Hugging Face provider terms.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default: smaller Wan 1.3B — live on fal-ai per Hub mapping (cheaper/faster smoke)
_DEFAULT_MODEL = "Wan-AI/Wan2.1-T2V-1.3B"
_DEFAULT_PROVIDER = "fal-ai"


def _hf_token() -> str:
    return (
        (os.getenv("HF_TOKEN") or "").strip()
        or (os.getenv("HUGGINGFACE_HUB_TOKEN") or "").strip()
        or (os.getenv("HUGGING_FACE_HUB_TOKEN") or "").strip()
    )


def _cfg_model() -> str:
    return (os.getenv("MIRA_HF_T2V_MODEL") or _DEFAULT_MODEL).strip() or _DEFAULT_MODEL


def _cfg_provider() -> str:
    return (os.getenv("MIRA_HF_T2V_PROVIDER") or _DEFAULT_PROVIDER).strip() or _DEFAULT_PROVIDER


def _cfg_num_frames() -> int | None:
    raw = (os.getenv("MIRA_HF_T2V_NUM_FRAMES") or "").strip()
    if not raw:
        return 25  # short default — fewer credits / faster
    try:
        n = int(raw)
        return max(8, min(121, n))
    except ValueError:
        return 25


def _cfg_timeout() -> float:
    try:
        return max(60.0, float(os.getenv("MIRA_HF_T2V_TIMEOUT_SEC") or "480"))
    except ValueError:
        return 480.0


def _hub_available() -> bool:
    try:
        import huggingface_hub  # noqa: F401

        return True
    except Exception:
        return False


def _looks_like_mp4(data: bytes) -> bool:
    if not data or len(data) < 12:
        return False
    # ISO BMFF: ....ftyp
    if len(data) >= 8 and data[4:8] == b"ftyp":
        return True
    if data[:3] == b"\x00\x00\x00" and b"ftyp" in data[:64]:
        return True
    return False


class HuggingFaceTextToVideoProvider:
    """Remote neural text-to-video via Hugging Face Inference Providers."""

    provider_id = "mira_hf_remote_t2v"

    def is_available(self) -> bool:
        if not _hf_token():
            return False
        if not _hub_available():
            return False
        return True

    def unavailable_reason(self) -> str:
        if not _hf_token():
            return "HF_TOKEN missing — add a Hugging Face token with Inference Providers permission."
        if not _hub_available():
            return "huggingface_hub not installed — run: pip install huggingface_hub"
        return "Hugging Face text-to-video provider not available."

    def generate(self, request: Any) -> dict[str, Any]:
        from jarvis.mira.generation_provider import VideoGenerationRequest
        from jarvis.mira.pipeline import out_root

        if not isinstance(request, VideoGenerationRequest):
            # duck-typed
            pass

        if not self.is_available():
            return {
                "ok": False,
                "status": "unavailable",
                "message": self.unavailable_reason()[:320],
                "provider": self.provider_id,
                "generation_kind": "remote_t2v",
                "is_neural_video": False,
                "notes": ["hf_t2v=unavailable"],
            }

        meta = getattr(request, "meta", None) or {}
        scenes = list(meta.get("scenes") or [])
        if not scenes:
            scenes = [
                {
                    "scene_id": "s01",
                    "visual_prompt": getattr(request, "brief", "") or "cinematic scene",
                    "narration": getattr(request, "brief", "") or "",
                    "role": "hook",
                    "search_query": getattr(request, "brief", "") or "",
                }
            ]

        root = out_root()
        work = root / "clips" / f"hf_t2v_{uuid.uuid4().hex[:10]}"
        work.mkdir(parents=True, exist_ok=True)
        notes: list[str] = [
            f"hf_model={_cfg_model()}",
            f"hf_provider={_cfg_provider()}",
            f"hf_num_frames={_cfg_num_frames()}",
        ]
        clip_paths: list[Path] = []
        handled: list[str] = []
        scene_errors: list[str] = []
        t0 = time.time()

        # Cap scenes for cost/time — full plan still used for VO; visuals for first N
        max_scenes = 4
        try:
            max_scenes = max(1, min(8, int(os.getenv("MIRA_HF_T2V_MAX_SCENES") or "4")))
        except ValueError:
            max_scenes = 4

        try:
            from jarvis.tools.mira_jobs import set_progress

            set_progress(
                f"HF remote T2V: generating up to {min(len(scenes), max_scenes)} neural clips…"
            )
        except Exception:
            pass

        for i, sc in enumerate(scenes[:max_scenes]):
            if not isinstance(sc, dict):
                continue
            sid = str(sc.get("scene_id") or f"s{i+1:02d}")
            prompt = str(sc.get("visual_prompt") or sc.get("search_query") or request.brief or "").strip()
            if not prompt:
                scene_errors.append(f"{sid}:empty_prompt")
                continue
            dest = work / f"{sid}_{uuid.uuid4().hex[:6]}.mp4"
            try:
                from jarvis.tools.mira_jobs import set_progress

                set_progress(f"HF T2V scene {i+1}/{min(len(scenes), max_scenes)}: {prompt[:60]}…")
            except Exception:
                pass
            try:
                self._generate_one_clip(prompt, dest)
                if dest.is_file() and dest.stat().st_size > 8_000 and _looks_like_mp4(dest.read_bytes()[:64]):
                    clip_paths.append(dest)
                    handled.append(sid)
                    # Attach path onto scene for composer
                    sc["neural_clip"] = str(dest)
                else:
                    scene_errors.append(f"{sid}:invalid_or_tiny_mp4")
                    dest.unlink(missing_ok=True)
            except Exception as exc:
                logger.warning("HF T2V scene %s failed: %s", sid, exc)
                scene_errors.append(f"{sid}:{type(exc).__name__}:{exc}"[:160])
                try:
                    dest.unlink(missing_ok=True)
                except Exception:
                    pass

        notes.append(f"hf_clips_ok={len(clip_paths)}")
        if scene_errors:
            notes.append(f"hf_scene_errors={scene_errors[:4]}")

        if not clip_paths:
            # cleanup empty work dir
            try:
                for p in work.glob("*"):
                    p.unlink(missing_ok=True)
                work.rmdir()
            except Exception:
                pass
            return {
                "ok": False,
                "status": "error",
                "message": (
                    "Hugging Face text-to-video produced no usable clips. "
                    f"{('; '.join(scene_errors[:3]) or 'unknown error')}"
                )[:320],
                "provider": self.provider_id,
                "generation_kind": "remote_t2v",
                "is_neural_video": False,
                "notes": notes,
                "scenes_handled": handled,
            }

        # Compose neural clips + Edge TTS via shared composer
        from jarvis.mira.creative_compose import compose_from_visual_paths

        # Map scenes to visuals (reuse narration from plan; pad remaining scenes with last clip)
        visual_by_sid = {}
        for sc in scenes[:max_scenes]:
            if isinstance(sc, dict) and sc.get("neural_clip"):
                visual_by_sid[str(sc.get("scene_id"))] = Path(str(sc["neural_clip"]))

        # If fewer clips than scenes, still compose handled scenes only
        compose_scenes = []
        for sc in scenes:
            if not isinstance(sc, dict):
                continue
            sid = str(sc.get("scene_id") or "")
            vis = visual_by_sid.get(sid)
            if not vis:
                continue
            compose_scenes.append({**sc, "visual_path": str(vis)})

        out = compose_from_visual_paths(
            request,
            compose_scenes,
            source_label="hf_remote_t2v",
            is_neural_video=True,
            generation_kind="remote_t2v",
            provider_id=self.provider_id,
        )
        out.setdefault("notes", [])
        out["notes"] = list(out.get("notes") or []) + notes
        out["hf_model"] = _cfg_model()
        out["hf_inference_provider"] = _cfg_provider()
        out["elapsed_sec"] = round(time.time() - t0, 1)
        if out.get("ok") and out.get("video_path"):
            out["is_neural_video"] = True
            out["generation_kind"] = "remote_t2v"
            out["provider"] = self.provider_id
        else:
            # Never claim neural success without a file
            out["is_neural_video"] = False
        return out

    def _generate_one_clip(self, prompt: str, dest: Path) -> Path:
        """Call HF InferenceClient.text_to_video and write MP4 bytes."""
        from huggingface_hub import InferenceClient

        token = _hf_token()
        model = _cfg_model()
        provider = _cfg_provider()
        num_frames = _cfg_num_frames()
        timeout = _cfg_timeout()

        client = InferenceClient(provider=provider, api_key=token, timeout=timeout)
        kwargs: dict[str, Any] = {"model": model}
        if num_frames is not None:
            kwargs["num_frames"] = float(num_frames)
        # Keep steps modest for cost/latency when env not set
        steps_raw = (os.getenv("MIRA_HF_T2V_STEPS") or "").strip()
        if steps_raw.isdigit():
            kwargs["num_inference_steps"] = max(4, min(50, int(steps_raw)))

        video = client.text_to_video(prompt[:800], **kwargs)
        data = _coerce_video_bytes(video)
        if not data:
            raise RuntimeError("HF text_to_video returned empty payload")
        if len(data) < 8_000:
            raise RuntimeError(f"HF video too small ({len(data)} bytes)")
        if not _looks_like_mp4(data[:64]):
            # Still save if large — some providers return mp4 without early ftyp
            logger.warning("HF payload missing early ftyp marker (%s bytes)", len(data))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return dest


def _coerce_video_bytes(video: Any) -> bytes:
    if video is None:
        return b""
    if isinstance(video, (bytes, bytearray)):
        return bytes(video)
    if isinstance(video, memoryview):
        return video.tobytes()
    # Path-like
    if isinstance(video, (str, Path)):
        p = Path(video)
        if p.is_file():
            return p.read_bytes()
    # file-like
    read = getattr(video, "read", None)
    if callable(read):
        data = read()
        if isinstance(data, (bytes, bytearray)):
            return bytes(data)
    raise RuntimeError(f"Unsupported HF video payload type: {type(video)}")
