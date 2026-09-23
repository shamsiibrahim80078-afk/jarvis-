"""Mira Creative Model facade for Jarvis — generate images/videos locally."""

from __future__ import annotations

from typing import Any

from jarvis.mira import feedback as mira_feedback
from jarvis.mira import pipeline
from jarvis.mira.quality import load_engine_config, load_learning_config

MODEL_NAME = "Mira Creative Model"
MODEL_ID = "mira_jarvis_v8"
MODEL_TAGLINE = (
    "Mira (Jarvis) — complete video/image agent: plan → fetch → compile → verify → fix. "
    "Formats (YT/Shorts/Reels/Stories), mood, edit/convert, uploads. "
    "Not a Veo/Sora-scale neural video model — the agent layer that matches the user's exact ask."
)


def model_identity() -> dict[str, Any]:
    learn = load_learning_config()
    pexels_on = False
    try:
        from jarvis.mira.pexels import configured

        pexels_on = configured()
    except Exception:
        pass
    return {
        "mira_model": MODEL_NAME,
        "model_id": MODEL_ID,
        "tagline": MODEL_TAGLINE,
        "kind": "first_party_pipeline",
        "is_trained_foundation_model": False,
        "rated_examples": learn.get("rated_examples") or 0,
        "out_dir": str(pipeline.out_root()),
        "pexels": pexels_on,
        "still_backends": ["pexels", "pollinations"] if pexels_on else ["pollinations"],
    }


def generate(intent: str, topic: str = "", **opts: Any) -> dict[str, Any]:
    """Route create_image / create_video / rate / help."""
    route = (intent or "help").strip().lower()
    topic = str(topic or opts.get("topic") or "").strip()
    brand = {
        "mira_model": MODEL_NAME,
        "model_id": MODEL_ID,
        "mira_engine": True,
        "is_trained_foundation_model": False,
    }

    if route in ("create_image", "image", "img"):
        out = pipeline.run_image(
            topic,
            style=str(opts.get("style") or "cinematic"),
            width=int(opts.get("width") or 1280),
            height=int(opts.get("height") or 720),
        )
    elif route in ("create_video", "video", "vid"):
        out = pipeline.run_video(
            topic,
            script=opts.get("script"),
            duration_sec=int(opts.get("duration_sec") or 30),
            n_stills=opts.get("n_stills"),
            aspect=str(opts.get("aspect") or "16:9"),
            style=str(opts.get("style") or "cinematic"),
            voice=opts.get("voice"),
            audio_mode=str(opts.get("audio_mode") or "voice"),
            media_paths=opts.get("media_paths"),
            use_uploads=bool(opts.get("use_uploads")),
            search_hints=opts.get("search_hints"),
            force_character=bool(opts.get("force_character")),
            mood=str(opts.get("mood") or "") or None,
            fit_mode=str(opts.get("fit_mode") or "") or None,
        )
    elif route in ("rate", "feedback"):
        out = mira_feedback.rate(
            int(opts.get("rating") or 3),
            topic=topic,
            prompt=str(opts.get("prompt") or ""),
            style=str(opts.get("style") or "cinematic"),
            path=str(opts.get("path") or ""),
            note=str(opts.get("note") or ""),
        )
    elif route == "status":
        out = {**model_identity(), "ok": True, "config": load_engine_config()}
    else:
        out = {
            "ok": True,
            "status": "ok",
            "action": "help",
            "message": (
                f"{MODEL_NAME}: say create_image / create_video with a topic. "
                "Rate outputs 1–5 so quality improves for your audience."
            ),
            "identity": model_identity(),
        }

    if isinstance(out, dict):
        for k, v in brand.items():
            out.setdefault(k, v)
    return out


def status() -> dict[str, Any]:
    return {**model_identity(), "ok": True, "message": MODEL_TAGLINE}
