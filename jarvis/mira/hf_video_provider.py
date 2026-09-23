"""Hugging Face Inference Providers — remote text-to-video for Mira.

Uses HF router → fal-ai queue for text-to-video.
Requires ``HF_TOKEN`` with Inference Providers permission.

Response handling is robust to:
- success payloads ``{ "video": { "url": ... } }``
- alternate URL shapes
- error payloads ``{ "detail": ... }`` (Hub client otherwise raises KeyError: 'video')

Known Hub mapping issue: ``Wan-AI/Wan2.1-T2V-1.3B`` currently maps to
``fal-ai/wan/v2.1/1.3b/text-to-video`` which fal returns as path-not-found.
That stale provider id is remapped to the live ``fal-ai/wan-t2v`` endpoint
(same Wan 2.1 family route Hub already uses for ``Wan-AI/Wan2.1-T2V-14B``).
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Default: Wan 1.3B Hub id (fal provider id remapped when Hub mapping is stale)
_DEFAULT_MODEL = "Wan-AI/Wan2.1-T2V-1.3B"
_DEFAULT_PROVIDER = "fal-ai"

# Hub currently maps 1.3B → this dead fal path (returns {"detail":"Path ... not found"})
_STALE_FAL_PROVIDER_IDS = {
    "fal-ai/wan/v2.1/1.3b/text-to-video": "fal-ai/wan-t2v",
}
_DEFAULT_FAL_FALLBACK = "fal-ai/wan-t2v"


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


def _resolve_fal_provider_id(hf_model: str) -> tuple[str, list[str]]:
    """Resolve fal provider id from Hub mapping; remap known-stale paths."""
    notes: list[str] = []
    override = (os.getenv("MIRA_HF_T2V_FAL_PROVIDER_ID") or "").strip()
    if override:
        notes.append(f"hf_fal_id_override={override}")
        return override, notes

    provider_id = ""
    try:
        from huggingface_hub import HfApi

        api = HfApi(token=_hf_token() or None)
        info = api.model_info(hf_model, expand=["inferenceProviderMapping"])
        mapping = getattr(info, "inference_provider_mapping", None) or []
        for m in mapping:
            if getattr(m, "provider", None) == "fal-ai" and getattr(m, "task", None) == "text-to-video":
                provider_id = str(getattr(m, "provider_id", "") or "")
                break
    except Exception as exc:
        logger.warning("HF model mapping lookup failed: %s", exc)
        notes.append(f"hf_mapping_lookup_failed={type(exc).__name__}")

    if not provider_id:
        provider_id = _DEFAULT_FAL_FALLBACK
        notes.append(f"hf_fal_id_default={provider_id}")

    remapped = _STALE_FAL_PROVIDER_IDS.get(provider_id)
    if remapped:
        notes.append(f"hf_fal_id_stale={provider_id}")
        notes.append(f"hf_fal_id_remap={remapped}")
        provider_id = remapped
    else:
        notes.append(f"hf_fal_id={provider_id}")
    return provider_id, notes


def _extract_video_url(result: Any) -> str:
    """Extract a downloadable video URL from fal / HF router result JSON."""
    if not isinstance(result, dict):
        raise RuntimeError(f"HF/fal T2V result is not a dict ({type(result).__name__})")

    # Error payloads (this is what caused KeyError: 'video' in huggingface_hub)
    if "detail" in result and "video" not in result and "videos" not in result:
        detail = result.get("detail")
        raise RuntimeError(f"HF/fal T2V error: {detail}")
    if result.get("error") and "video" not in result:
        raise RuntimeError(f"HF/fal T2V error: {result.get('error')}")

    video = result.get("video")
    if isinstance(video, dict):
        url = video.get("url") or video.get("video_url") or video.get("file")
        if isinstance(url, str) and url.strip():
            return url.strip()
    if isinstance(video, str) and video.strip():
        return video.strip()

    for key in ("video_url", "url"):
        val = result.get(key)
        if isinstance(val, str) and val.startswith(("http://", "https://", "data:")):
            return val

    videos = result.get("videos")
    if isinstance(videos, list) and videos:
        first = videos[0]
        if isinstance(first, dict):
            url = first.get("url") or first.get("video_url")
            if isinstance(url, str) and url.strip():
                return url.strip()
        if isinstance(first, str) and first.strip():
            return first.strip()

    nested = result.get("output")
    if isinstance(nested, dict):
        return _extract_video_url(nested)

    raise RuntimeError(
        "HF/fal T2V response missing video URL "
        f"(keys={sorted(result.keys())[:12]})"
    )


def _download_url_bytes(url: str, *, timeout: float) -> bytes:
    from huggingface_hub.utils import get_session, hf_raise_for_status

    if url.startswith("data:"):
        # data:[<mediatype>][;base64],<data>
        import base64

        try:
            header, b64 = url.split(",", 1)
        except ValueError as exc:
            raise RuntimeError("Invalid data URL in fal video response") from exc
        if ";base64" not in header:
            raise RuntimeError("Unsupported non-base64 data URL for fal video")
        return base64.b64decode(b64)

    session = get_session()
    resp = session.get(url, timeout=timeout)
    hf_raise_for_status(resp)
    return resp.content


def _video_bytes_from_provider_payload(payload: Any, *, timeout: float) -> bytes:
    """Normalize InferenceClient / fal payloads into raw video bytes."""
    if isinstance(payload, (bytes, bytearray, memoryview)):
        data = bytes(payload)
        if data:
            return data
        raise RuntimeError("HF text_to_video returned empty bytes")

    if isinstance(payload, dict):
        url = _extract_video_url(payload)
        return _download_url_bytes(url, timeout=timeout)

    # Path / file-like
    if isinstance(payload, (str, Path)):
        p = Path(payload)
        if p.is_file():
            return p.read_bytes()
        if isinstance(payload, str) and payload.startswith(("http://", "https://", "data:")):
            return _download_url_bytes(payload, timeout=timeout)

    read = getattr(payload, "read", None)
    if callable(read):
        data = read()
        if isinstance(data, (bytes, bytearray)):
            return bytes(data)

    raise RuntimeError(f"Unsupported HF video payload type: {type(payload)}")


def _fal_ai_text_to_video_via_hf_router(
    prompt: str,
    *,
    hf_model: str,
    num_frames: int | None,
    timeout: float,
    extra: dict[str, Any] | None = None,
) -> tuple[bytes, list[str]]:
    """Submit fal text-to-video through HF Inference Providers router + parse result."""
    from huggingface_hub.utils import get_session, hf_raise_for_status

    notes: list[str] = []
    provider_id, map_notes = _resolve_fal_provider_id(hf_model)
    notes.extend(map_notes)

    frames = int(num_frames) if num_frames is not None else 25
    # fal-ai/wan-t2v documents ~81–100 frames; clamp only for that live endpoint
    if provider_id.rstrip("/").endswith("wan-t2v") and frames < 81:
        notes.append(f"hf_frames_clamped_from={frames}")
        frames = 81
        notes.append("hf_frames_clamped_to=81")

    token = _hf_token()
    submit_url = f"https://router.huggingface.co/fal-ai/{provider_id}?_subdomain=queue"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload: dict[str, Any] = {"prompt": prompt[:800], "num_frames": frames}
    # Prefer cheap/low res when supported by wan-t2v
    payload.setdefault("resolution", (os.getenv("MIRA_HF_T2V_RESOLUTION") or "480p").strip() or "480p")
    payload.setdefault("aspect_ratio", (os.getenv("MIRA_HF_T2V_ASPECT") or "16:9").strip() or "16:9")
    if extra:
        payload.update(extra)

    session = get_session()
    logger.info("HF fal T2V submit provider_id=%s frames=%s", provider_id, frames)
    post = session.post(submit_url, headers=headers, json=payload, timeout=min(120.0, timeout))
    hf_raise_for_status(post)
    try:
        body = post.json()
    except Exception as exc:
        raise RuntimeError("HF/fal T2V submit returned non-JSON") from exc

    if isinstance(body, dict) and body.get("detail") and not body.get("request_id"):
        raise RuntimeError(f"HF/fal T2V submit error: {body.get('detail')}")

    if not isinstance(body, dict) or not body.get("request_id"):
        # Some routes may return the final payload immediately
        data = _video_bytes_from_provider_payload(body, timeout=timeout)
        return data, notes

    # Queue poll (mirrors huggingface_hub FalAIQueueTask)
    parsed = urlparse(submit_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}/fal-ai"
    query = f"?{parsed.query}" if parsed.query else ""
    model_path = urlparse(str(body.get("response_url") or "")).path
    if not model_path:
        raise RuntimeError("HF/fal T2V queue response missing response_url")
    status_url = f"{base_url}{model_path}/status{query}"
    result_url = f"{base_url}{model_path}{query}"

    status = body.get("status")
    t0 = time.time()
    while status != "COMPLETED":
        if time.time() - t0 > timeout:
            raise RuntimeError(f"HF/fal T2V timed out after {timeout:.0f}s (last_status={status})")
        time.sleep(1.0)
        status_resp = session.get(status_url, headers=headers, timeout=60)
        hf_raise_for_status(status_resp)
        try:
            status = status_resp.json().get("status")
        except Exception as exc:
            raise RuntimeError("HF/fal T2V status returned non-JSON") from exc
        if status in ("FAILED", "ERROR", "CANCELLED"):
            raise RuntimeError(f"HF/fal T2V queue failed (status={status})")

    result_resp = session.get(result_url, headers=headers, timeout=min(120.0, timeout))
    hf_raise_for_status(result_resp)
    try:
        result = result_resp.json()
    except Exception as exc:
        # Rare: raw bytes
        content = result_resp.content
        if content and _looks_like_mp4(content[:64]):
            return content, notes
        raise RuntimeError("HF/fal T2V result returned non-JSON") from exc

    data = _video_bytes_from_provider_payload(result, timeout=timeout)
    notes.append(f"hf_video_bytes={len(data)}")
    return data, notes


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
                clip_notes = self._generate_one_clip(prompt, dest)
                notes.extend(clip_notes)
                if dest.is_file() and dest.stat().st_size > 8_000 and _looks_like_mp4(dest.read_bytes()[:64]):
                    clip_paths.append(dest)
                    handled.append(sid)
                    sc["neural_clip"] = str(dest)
                else:
                    scene_errors.append(f"{sid}:invalid_or_tiny_mp4")
                    dest.unlink(missing_ok=True)
            except Exception as exc:
                logger.warning("HF T2V scene %s failed: %s", sid, exc)
                scene_errors.append(f"{sid}:{type(exc).__name__}:{exc}"[:200])
                try:
                    dest.unlink(missing_ok=True)
                except Exception:
                    pass

        notes.append(f"hf_clips_ok={len(clip_paths)}")
        if scene_errors:
            notes.append(f"hf_scene_errors={scene_errors[:4]}")

        if not clip_paths:
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
                )[:360],
                "provider": self.provider_id,
                "generation_kind": "remote_t2v",
                "is_neural_video": False,
                "notes": notes,
                "scenes_handled": handled,
            }

        from jarvis.mira.creative_compose import compose_from_visual_paths

        visual_by_sid = {}
        for sc in scenes[:max_scenes]:
            if isinstance(sc, dict) and sc.get("neural_clip"):
                visual_by_sid[str(sc.get("scene_id"))] = Path(str(sc["neural_clip"]))

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
        # Strict: only claim neural after real composed file exists
        vpath = out.get("video_path")
        if (
            out.get("ok")
            and vpath
            and Path(str(vpath)).is_file()
            and Path(str(vpath)).stat().st_size > 8_000
        ):
            out["is_neural_video"] = True
            out["generation_kind"] = "remote_t2v"
            out["provider"] = self.provider_id
        else:
            out["is_neural_video"] = False
        return out

    def _generate_one_clip(self, prompt: str, dest: Path) -> list[str]:
        """Generate one scene clip; return extra notes. Raises on failure."""
        model = _cfg_model()
        provider = _cfg_provider()
        num_frames = _cfg_num_frames()
        timeout = _cfg_timeout()
        notes: list[str] = []

        if provider == "fal-ai":
            data, call_notes = _fal_ai_text_to_video_via_hf_router(
                prompt,
                hf_model=model,
                num_frames=num_frames,
                timeout=timeout,
            )
            notes.extend(call_notes)
        else:
            # Non-fal providers: use InferenceClient, then normalize payload
            from huggingface_hub import InferenceClient

            client = InferenceClient(provider=provider, api_key=_hf_token(), timeout=timeout)
            kwargs: dict[str, Any] = {"model": model}
            if num_frames is not None:
                kwargs["num_frames"] = float(num_frames)
            steps_raw = (os.getenv("MIRA_HF_T2V_STEPS") or "").strip()
            if steps_raw.isdigit():
                kwargs["num_inference_steps"] = max(4, min(50, int(steps_raw)))
            try:
                video = client.text_to_video(prompt[:800], **kwargs)
            except KeyError as exc:
                raise RuntimeError(
                    "HF text_to_video response missing expected field "
                    f"{exc!s} (provider returned an error or non-video payload)"
                ) from exc
            data = _video_bytes_from_provider_payload(video, timeout=timeout)

        if not data:
            raise RuntimeError("HF text_to_video returned empty payload")
        if len(data) < 8_000:
            raise RuntimeError(f"HF video too small ({len(data)} bytes)")
        if not _looks_like_mp4(data[:64]):
            logger.warning("HF payload missing early ftyp marker (%s bytes)", len(data))
            raise RuntimeError("HF video payload does not look like a valid MP4")

        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        if not dest.is_file() or dest.stat().st_size < 8_000:
            raise RuntimeError("Failed to write HF video to disk")
        return notes


# Back-compat alias used by older tests / imports
def _coerce_video_bytes(video: Any) -> bytes:
    return _video_bytes_from_provider_payload(video, timeout=_cfg_timeout())
