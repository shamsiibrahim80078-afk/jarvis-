"""Live Mira uploads-first video test — download sample media, upload, generate via API."""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

BASE = "http://127.0.0.1:8765"


def http_json(method: str, path: str, body: dict | None = None, timeout: float = 60.0):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", errors="replace")
        return r.status, json.loads(raw) if raw else {}


def download(url: str, dest: Path, timeout: float = 60.0) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  DL {url[:80]}… → {dest.name}", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Jarvis-Mira-Test/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        dest.write_bytes(r.read())
    print(f"  OK {dest.name} ({dest.stat().st_size} bytes)", flush=True)
    return dest


def fetch_pexels_samples(out: Path) -> list[Path]:
    from jarvis.mira import pexels as px

    if not px.configured():
        print("PEXELS not configured — using public sample URLs", flush=True)
        return []
    paths: list[Path] = []
    # 2 short video clips
    vids = px.search_videos("ocean waves cinematic", count=2, orientation="portrait")
    for i, v in enumerate(vids[:2]):
        url = v.get("url")
        if not url:
            continue
        dest = out / f"sample_ocean_{i + 1}.mp4"
        try:
            download(str(url), dest)
            paths.append(dest)
        except Exception as exc:
            print(f"  skip video: {exc}", flush=True)
    # 2 stills
    photos = px.search_photos("coffee shop latte", count=2, orientation="portrait")
    for i, ph in enumerate(photos[:2]):
        url = ph.get("url") or ph.get("src") or ""
        if isinstance(ph.get("src"), dict):
            url = ph["src"].get("large") or ph["src"].get("original") or ""
        if not url:
            continue
        dest = out / f"sample_coffee_{i + 1}.jpg"
        try:
            download(str(url), dest)
            paths.append(dest)
        except Exception as exc:
            print(f"  skip photo: {exc}", flush=True)
    return paths


def fetch_public_fallbacks(out: Path) -> list[Path]:
    """Public sample media if Pexels fails."""
    samples = [
        (
            "https://images.pexels.com/photos/302899/pexels-photo-302899.jpeg?auto=compress&cs=tinysrgb&w=800",
            "fallback_coffee.jpg",
        ),
        (
            "https://images.pexels.com/photos/1001682/pexels-photo-1001682.jpeg?auto=compress&cs=tinysrgb&w=800",
            "fallback_ocean.jpg",
        ),
        (
            "https://images.pexels.com/photos/3184292/pexels-photo-3184292.jpeg?auto=compress&cs=tinysrgb&w=800",
            "fallback_desk.jpg",
        ),
    ]
    paths: list[Path] = []
    for url, name in samples:
        dest = out / name
        try:
            download(url, dest)
            paths.append(dest)
        except Exception as exc:
            print(f"  fallback fail {name}: {exc}", flush=True)
    return paths


def upload_files(paths: list[Path]) -> dict:
    """POST multipart to /api/mira/upload."""
    import uuid

    boundary = f"----Jarvis{uuid.uuid4().hex}"
    body = bytearray()
    for p in paths:
        ctype = "video/mp4" if p.suffix.lower() == ".mp4" else "image/jpeg"
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            f'Content-Disposition: form-data; name="files"; filename="{p.name}"\r\n'.encode()
        )
        body.extend(f"Content-Type: {ctype}\r\n\r\n".encode())
        body.extend(p.read_bytes())
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        BASE + "/api/mira/upload",
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


def main() -> int:
    print("=== LIVE MIRA UPLOADS → VIDEO TEST ===", flush=True)
    st, health = http_json("GET", "/api/health", timeout=15)
    print("health", health, flush=True)

    staging = ROOT / "data" / "mira" / "_live_test_media"
    staging.mkdir(parents=True, exist_ok=True)

    print("\n1) Fetch sample clips/images from Pexels…", flush=True)
    paths = fetch_pexels_samples(staging)
    if len(paths) < 2:
        print("  topping up with public stills…", flush=True)
        paths.extend(fetch_public_fallbacks(staging))
    # Also copy any existing mira videos as extra clips
    vid_dir = ROOT / "data" / "mira" / "videos"
    if vid_dir.is_dir():
        for p in sorted(vid_dir.glob("*.mp4"))[:2]:
            dest = staging / f"reuse_{p.name}"
            if not dest.is_file():
                dest.write_bytes(p.read_bytes())
            paths.append(dest)
            print(f"  reuse existing {p.name}", flush=True)

    paths = [p for p in paths if p.is_file() and p.stat().st_size > 1000][:6]
    print(f"\n2) Uploading {len(paths)} files to Mira…", flush=True)
    for p in paths:
        print(f"  - {p.name} ({p.stat().st_size} bytes)", flush=True)
    if not paths:
        print("FAIL: no media to upload", flush=True)
        return 1

    up = upload_files(paths)
    print("upload:", json.dumps({k: up.get(k) for k in ("ok", "count", "message")}, indent=2), flush=True)

    print("\n3) Start Mira job (uploads-first)…", flush=True)
    msg = (
        "make a mute 15 second youtube short about ocean coffee morning vibe "
        "using my uploads"
    )
    st, start = http_json("POST", "/api/mira", {"message": msg}, timeout=45)
    print("start:", start.get("response") or start, flush=True)

    print("\n4) Poll /api/mira-status — watch HUD Agent Town / Mira…", flush=True)
    last = {}
    for i in range(60):
        time.sleep(3)
        try:
            _, last = http_json("GET", "/api/mira-status", timeout=15)
        except Exception as exc:
            print(f"  poll {i} error {exc}", flush=True)
            continue
        status = last.get("status")
        running = last.get("running")
        media = last.get("media_url") or last.get("media_path")
        resp = str(last.get("response") or "")[:100]
        print(f"  poll {i}: status={status} running={running} media={media} | {resp}", flush=True)
        if status in ("done", "error", "failed") and running is False:
            break
        if status == "done" and media:
            break

    print("\n=== RESULT ===", flush=True)
    print(json.dumps(last, indent=2)[:1200], flush=True)
    media_url = last.get("media_url")
    if last.get("status") == "done" and (media_url or last.get("media_path")):
        print(f"\nOPEN IN BROWSER: {media_url or last.get('media_path')}", flush=True)
        print("HUD: http://127.0.0.1:8765/?v=60", flush=True)
        return 0
    print("FAIL or incomplete — check Mira status on HUD", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
