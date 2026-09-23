"""FastAPI backend for Jarvis web UI."""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

from jarvis.api.core import get_core
from jarvis.api.tts import generate_tts_audio
from jarvis.fast_router import is_human_view_command, is_wake_only, try_fast_command
from jarvis.tools.api_hunter import fetch_api_key
from jarvis.tools.api_intent import is_api_hunt_intent
from jarvis.tools.api_pipeline import is_api_count_command, is_batch_api_command
from jarvis.tools.command_parse import is_sheet_context_command
from jarvis.tools.screen_share import (
    get_jarvis_frame,
    get_status as screen_status,
    handle_screen_share_command,
    is_screen_share_command,
    set_user_frame,
    start_jarvis_share,
    start_user_share,
    stop_jarvis_share,
    stop_user_share,
)
from jarvis.tools.task_executor import try_task_command

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("jarvis.api")
WEB_DIR = ROOT / "web"

# Dedicated pool so sheet/Chrome/network work cannot starve command handling
_COMMAND_POOL = ThreadPoolExecutor(max_workers=16, thread_name_prefix="jarvis-cmd")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Jarvis API starting")
    crew_q: queue.Queue = queue.Queue()

    def _on_crew(event: dict) -> None:
        try:
            crew_q.put_nowait(event)
        except Exception:
            pass

    try:
        from jarvis.crew import bus as crew_bus
        from jarvis.crew.ambient import start_ambient
        from jarvis.mira.schedule import ensure_worker, get_status

        crew_bus.add_listener(_on_crew)
        start_ambient()
        crew_bus.emit(
            "system",
            from_id="jarvis",
            text="Agents Workspace online. Mira is on the studio floor.",
        )

        st = get_status()
        if st.get("enabled") and st.get("topics"):
            ensure_worker()
            logger.info(
                "Growth schedule resumed (%s topics, every %sh)",
                len(st.get("topics") or []),
                st.get("interval_hours"),
            )
        else:
            ensure_worker()
    except Exception as exc:
        logger.warning("Crew/schedule startup issue: %s", exc)

    async def _crew_pump() -> None:
        speak_path = ROOT / "data" / "speak_queue.jsonl"
        last_spoken = ""
        last_spoken_at = 0.0
        while True:
            await asyncio.sleep(0.25)
            while True:
                try:
                    ev = crew_q.get_nowait()
                except queue.Empty:
                    break
                try:
                    await manager.broadcast({"type": "crew", "event": ev})
                except Exception:
                    pass
            # Drain Mira speak queue so Owner hears Jarvis during live jobs
            try:
                if speak_path.is_file():
                    raw = speak_path.read_text(encoding="utf-8")
                    speak_path.write_text("", encoding="utf-8")
                    now = time.time()
                    for line in raw.splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            payload = json.loads(line)
                        except Exception:
                            continue
                        text = str(payload.get("text") or "").strip()[:160]
                        if not text or text == last_spoken:
                            continue
                        if now - last_spoken_at < 3.5:
                            continue
                        last_spoken = text
                        last_spoken_at = now
                        try:
                            await manager.broadcast(
                                {"type": "speak", "text": text, "chat": True}
                            )
                            await manager.broadcast(
                                {"type": "status", "status": "SPEAKING"}
                            )
                        except Exception:
                            pass
            except Exception:
                pass

    pump_task = asyncio.create_task(_crew_pump())
    yield
    pump_task.cancel()
    logger.info("Jarvis API stopped")
    try:
        from jarvis.crew.ambient import stop_ambient
        from jarvis.mira.schedule import shutdown_worker

        stop_ambient()
        shutdown_worker()
    except Exception:
        pass
    _COMMAND_POOL.shutdown(wait=False)


app = FastAPI(title="Jarvis API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class CommandRequest(BaseModel):
    message: str
    speak: bool = True


class TTSRequest(BaseModel):
    text: str


class ScreenFrameB64(BaseModel):
    image_b64: str


class ConnectionManager:
    def __init__(self) -> None:
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, data: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        for ws in list(self.active):
            try:
                await asyncio.wait_for(ws.send_json(data), timeout=1.5)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/workspace")
async def agents_workspace() -> FileResponse:
    # Company floor now lives on the main Jarvis landing (reel layout)
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/crew/state")
async def crew_state() -> dict:
    from jarvis.crew import bus

    return bus.get_state()


@app.get("/api/crew/events")
async def crew_events(since: int = 0) -> dict:
    from jarvis.crew import bus

    return {"events": bus.events_since(since)}


@app.post("/api/crew/command")
async def crew_command(req: CommandRequest) -> dict:
    """Owner command on Agents Workspace → Jarvis routes to workers."""
    loop = asyncio.get_event_loop()

    def _run():
        from jarvis.crew.dispatch import dispatch_owner_command

        return dispatch_owner_command(req.message, source="owner")

    out = await loop.run_in_executor(_COMMAND_POOL, _run)
    # If Jarvis should handle locally (non-agent), use fast/core path
    if out.get("handle_locally"):
        result = await loop.run_in_executor(_COMMAND_POOL, try_fast_command, req.message)
        if result:
            return {"response": result, "handled": True, **out}
        # brain fallback lightly
        try:
            from jarvis.api.core import get_core

            core_out = await loop.run_in_executor(
                _COMMAND_POOL, lambda: get_core().process(req.message)
            )
            return {
                "response": (core_out or {}).get("response") or out.get("message"),
                "handled": True,
                **out,
            }
        except Exception:
            pass
    return {
        "response": out.get("message") or "Assigned.",
        "handled": True,
        **out,
    }


@app.get("/face")
async def face_view() -> FileResponse:
    return FileResponse(WEB_DIR / "face.html")


@app.get("/api/health")
async def health() -> dict:
    return {"status": "online", "service": "jarvis"}


@app.get("/api/status")
async def status() -> dict:
    from jarvis.api.core import get_status_cached
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_COMMAND_POOL, get_status_cached)


@app.get("/api/briefing")
async def briefing() -> dict:
    loop = asyncio.get_event_loop()
    text = await loop.run_in_executor(_COMMAND_POOL, get_core().get_briefing)
    return {"response": text}


@app.get("/api/hunt-status")
async def hunt_status() -> dict:
    from jarvis.tools.hunt_bus import get_status
    return get_status()


@app.post("/api/hunt-reset")
async def hunt_reset() -> dict:
    from jarvis.tools.hunt_bus import force_reset
    force_reset()
    return {"status": "idle", "message": "Hunt state cleared, sir."}


@app.post("/api/hunt")
async def api_hunt(req: CommandRequest) -> dict:
    """API key hunter only — never calls Groq brain."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_COMMAND_POOL, fetch_api_key, req.message)
    return {"response": result, "source": "api_hunt", "handled": True}


@app.post("/api/fast")
async def fast_command(req: CommandRequest) -> dict:
    """Ultra-fast path — instant commands only, no AI."""
    loop = asyncio.get_event_loop()
    msg = req.message

    # Hard guards before anything else
    if is_wake_only(msg):
        return {"response": "Yes sir, how may I help you?", "source": "wake", "handled": True}
    # Remember links before hunt — "remember my api sheet is URL" must never hunt
    if "remember" in msg.lower():
        result = await loop.run_in_executor(_COMMAND_POOL, try_task_command, msg)
        if result:
            return {"response": result, "source": "task", "handled": True}
    # Scoped sheet batch BEFORE single-key hunt (phantom / from row N / paste)
    if is_batch_api_command(msg):
        result = await loop.run_in_executor(_COMMAND_POOL, try_fast_command, msg)
        if result:
            src = "sheet_batch" if ("api" in msg.lower() or "phantom" in msg.lower()) else "fast"
            return {"response": result, "source": src, "handled": True}
    if is_api_hunt_intent(msg):
        result = await loop.run_in_executor(_COMMAND_POOL, fetch_api_key, msg)
        return {"response": result, "source": "api_hunt", "handled": True}

    # Mira generate (any topic) — never fall through to YouTube search / brain
    from jarvis.tools.mira_tool import is_mira_followup_intent, is_mira_generate_intent, try_mira_command

    if is_mira_generate_intent(msg) or is_mira_followup_intent(msg):
        result = await loop.run_in_executor(
            _COMMAND_POOL, lambda: try_mira_command(msg, background=True)
        )
        if result:
            return {"response": result, "source": "mira", "handled": True}

    if is_api_count_command(msg):
        from jarvis.tools.api_pipeline import count_apis_from_sheet
        result = await loop.run_in_executor(_COMMAND_POOL, count_apis_from_sheet, msg)
        return {"response": result, "source": "api_count", "handled": True}
    if is_screen_share_command(msg):
        result = await loop.run_in_executor(_COMMAND_POOL, handle_screen_share_command, msg)
        if result:
            # Prompt HUD to open getDisplayMedia for user-share phrases
            lower = msg.lower()
            if any(p in lower for p in ("share my screen", "watch my screen", "watch me")):
                await manager.broadcast({"type": "screen_share_prompt", "mode": "user"})
            if any(p in lower for p in ("share your screen", "show me what you", "show your screen")):
                await manager.broadcast({"type": "screen_share_prompt", "mode": "jarvis"})
            return {"response": result, "source": "screen_share", "handled": True}
    if is_human_view_command(msg):
        result = await loop.run_in_executor(_COMMAND_POOL, try_fast_command, msg)
        if result:
            return {"response": result, "source": "fast", "handled": True}
    if is_sheet_context_command(msg):
        result = await loop.run_in_executor(_COMMAND_POOL, try_fast_command, msg)
        if result:
            return {"response": result, "source": "fast", "handled": True}
        result = await loop.run_in_executor(_COMMAND_POOL, try_task_command, msg)
        if result:
            return {"response": result, "source": "task", "handled": True}
        return {
            "response": (
                "No sheet saved yet, sir. Say 'remember my api sheet is [url]' first."
            ),
            "source": "fast",
            "handled": True,
        }

    result = await loop.run_in_executor(_COMMAND_POOL, try_fast_command, msg)
    if result:
        return {"response": result, "source": "fast", "handled": True}
    result = await loop.run_in_executor(_COMMAND_POOL, try_task_command, msg)
    if result:
        return {"response": result, "source": "task", "handled": True}
    return {"response": None, "source": "none", "handled": False}


@app.post("/api/command")
async def command(req: CommandRequest) -> dict:
    await manager.broadcast({"type": "status", "status": "THINKING"})
    await manager.broadcast({"type": "user", "text": req.message})

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_COMMAND_POOL, get_core().process, req.message)
    response = result["response"]

    await manager.broadcast({"type": "jarvis", "text": response})
    await manager.broadcast({"type": "status", "status": "ONLINE"})

    return {
        "response": response,
        "source": result["source"],
        "speak": False,
    }


@app.post("/api/mira")
async def mira_generate(req: CommandRequest) -> dict:
    """Start Mira image/video job in background (poll /api/mira-status)."""
    from jarvis.tools.mira_tool import try_mira_command

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        _COMMAND_POOL, lambda: try_mira_command(req.message, background=True)
    )
    if not result:
        return {
            "response": "Say make a video about … or create an image of …, sir.",
            "source": "mira",
            "handled": False,
        }
    # Make Jarvis speak in the open HUD so Owner hears generation start
    speak_line = (result or "").split(".")[0].strip()
    if speak_line:
        speak_line = speak_line[:120]
        if not speak_line.endswith((".", "!", "?")):
            speak_line += "."
        try:
            await manager.broadcast(
                {"type": "speak", "text": speak_line, "chat": True}
            )
            await manager.broadcast({"type": "status", "status": "SPEAKING"})
        except Exception:
            pass
    return {"response": result, "source": "mira", "handled": True}


@app.post("/api/speak")
async def api_speak(req: TTSRequest) -> dict:
    """Ask the open Jarvis HUD to speak (browser speechSynthesis)."""
    text = (req.text or "").strip()
    if not text:
        return {"ok": False, "message": "text required"}
    await manager.broadcast({"type": "speak", "text": text[:240], "chat": True})
    await manager.broadcast({"type": "status", "status": "SPEAKING"})
    return {"ok": True, "spoken": text[:240]}


@app.get("/api/mira-status")
async def mira_status_api() -> dict:
    from jarvis.tools.mira_jobs import get_status

    return get_status()


@app.post("/api/mira/upload")
async def mira_upload(files: list[UploadFile] = File(...)) -> dict:
    """Upload user images/videos for Mira to use in the next generate."""
    from jarvis.mira import uploads as uploads_mod

    saved: list[dict] = []
    errors: list[str] = []
    for uf in files or []:
        name = uf.filename or "media.bin"
        try:
            data = await uf.read()
            if len(data) > 200 * 1024 * 1024:
                errors.append(f"{name}: too large (max 200MB)")
                continue
            dest = uploads_mod.save_upload(name, data)
            saved.append(
                {
                    "name": dest.name,
                    "path": str(dest),
                    "kind": "video" if uploads_mod.is_video(dest) else "image",
                    "bytes": dest.stat().st_size,
                }
            )
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    return {
        "ok": bool(saved),
        "saved": saved,
        "errors": errors,
        "count": len(uploads_mod.list_uploads()),
        "folder": str(uploads_mod.uploads_dir()),
        "message": (
            f"Uploaded {len(saved)} file(s) — Mira will use YOUR media FIRST on the next video. "
            "Just say what you want (e.g. make a short about this trip). "
            "Say stock only to skip uploads."
            if saved
            else (errors[0] if errors else "No files saved")
        ),
    }


@app.get("/api/mira/uploads")
async def mira_list_uploads() -> dict:
    from jarvis.mira import uploads as uploads_mod

    rows = uploads_mod.list_uploads()
    return {
        "ok": True,
        "uploads": rows,
        "count": len(rows),
        "folder": str(uploads_mod.uploads_dir()),
    }


@app.post("/api/chat/paste-image")
async def chat_paste_image(
    file: UploadFile = File(...),
    question: str = Form(""),
) -> dict:
    """Paste/drop a screenshot in chat — save for Mira + vision-read text."""
    from jarvis.tools.screenshot_read import handle_paste

    data = await file.read()
    name = file.filename or "screenshot.png"
    q = (question or "").strip()
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        _COMMAND_POOL,
        lambda: handle_paste(data, name, question=q),
    )
    return result



@app.get("/mira/media/{kind}/{filename}")
async def mira_media_file(kind: str, filename: str) -> FileResponse:
    """Serve Mira videos/images/uploads so Chrome can open them."""
    kind = (kind or "").strip().lower()
    if kind not in ("videos", "images", "uploads"):
        return JSONResponse({"error": "invalid kind"}, status_code=400)
    # Prevent path traversal
    name = Path(filename).name
    if not name or name != filename.replace("\\", "/").split("/")[-1]:
        return JSONResponse({"error": "invalid filename"}, status_code=400)
    path = ROOT / "data" / "mira" / kind / name
    if not path.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    media = "video/mp4" if path.suffix.lower() == ".mp4" else "image/jpeg"
    if path.suffix.lower() == ".png":
        media = "image/png"
    elif path.suffix.lower() == ".webp":
        media = "image/webp"
    elif path.suffix.lower() in (".mov", ".webm", ".mkv", ".avi", ".m4v"):
        media = "video/mp4"
    return FileResponse(
        path,
        media_type=media,
        filename=name,
        headers={"Cache-Control": "no-cache", "Content-Disposition": f'inline; filename="{name}"'},
    )


@app.post("/api/tts")
async def tts_post(req: TTSRequest) -> Response:
    await manager.broadcast({"type": "status", "status": "SPEAKING"})
    audio, media = await generate_tts_audio(req.text)
    await manager.broadcast({"type": "status", "status": "ONLINE"})
    if not audio:
        return JSONResponse({"error": "TTS failed"}, status_code=500)
    return Response(
        content=audio,
        media_type=media,
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/api/tts")
async def tts_get(text: str) -> Response:
    await manager.broadcast({"type": "status", "status": "SPEAKING"})
    audio, media = await generate_tts_audio(text)
    await manager.broadcast({"type": "status", "status": "ONLINE"})
    if not audio:
        return JSONResponse({"error": "TTS failed"}, status_code=500)
    return Response(content=audio, media_type=media)


# ── Screen share ─────────────────────────────────────────

@app.get("/api/screen/status")
async def api_screen_status() -> dict:
    return screen_status()


@app.post("/api/screen/user/start")
async def api_user_share_start() -> dict:
    msg = start_user_share()
    await manager.broadcast({"type": "screen_share", "user": True})
    return {"response": msg, "status": screen_status()}


@app.post("/api/screen/user/stop")
async def api_user_share_stop() -> dict:
    msg = stop_user_share()
    await manager.broadcast({"type": "screen_share", "user": False})
    return {"response": msg, "status": screen_status()}


@app.post("/api/screen/user/frame")
async def api_user_frame(file: UploadFile = File(...)) -> dict:
    data = await file.read()
    if not data:
        return JSONResponse({"error": "empty frame"}, status_code=400)
    # Accept jpeg/png; store as-is (vision APIs accept jpeg; png ok for Gemini)
    set_user_frame(data)
    return {"ok": True, "bytes": len(data)}


@app.post("/api/screen/user/frame-b64")
async def api_user_frame_b64(req: ScreenFrameB64) -> dict:
    import base64
    raw = req.image_b64
    if "," in raw:
        raw = raw.split(",", 1)[1]
    try:
        data = base64.b64decode(raw)
    except Exception:
        return JSONResponse({"error": "bad base64"}, status_code=400)
    set_user_frame(data)
    return {"ok": True, "bytes": len(data)}


@app.post("/api/screen/jarvis/start")
async def api_jarvis_share_start() -> dict:
    msg = start_jarvis_share()
    await manager.broadcast({"type": "screen_share", "jarvis": True})
    return {"response": msg, "status": screen_status()}


@app.post("/api/screen/jarvis/stop")
async def api_jarvis_share_stop() -> dict:
    msg = stop_jarvis_share()
    await manager.broadcast({"type": "screen_share", "jarvis": False})
    return {"response": msg, "status": screen_status()}


@app.get("/api/screen/jarvis/frame")
async def api_jarvis_frame() -> Response:
    jpeg, ts, source = get_jarvis_frame()
    if not jpeg:
        return JSONResponse({"error": "no frame", "source": source}, status_code=404)
    return Response(
        content=jpeg,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-store, no-cache",
            "X-Frame-Source": source,
            "X-Frame-Age": str(round(time.time() - ts, 2) if ts else 0),
        },
    )


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await manager.connect(ws)
    core = get_core()
    await ws.send_json({"type": "connected", "status": core.get_status()})
    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            if msg.get("type") == "ping":
                await ws.send_json({"type": "pong"})
            elif msg.get("type") == "command":
                text = msg.get("text", "").strip()
                if not text:
                    continue
                await manager.broadcast({"type": "status", "status": "THINKING"})
                await manager.broadcast({"type": "user", "text": text})
                result = core.process(text)
                await manager.broadcast({"type": "jarvis", "text": result["response"]})
                await manager.broadcast({"type": "status", "status": "ONLINE"})
                await ws.send_json({"type": "result", **result})
    except WebSocketDisconnect:
        manager.disconnect(ws)


if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
