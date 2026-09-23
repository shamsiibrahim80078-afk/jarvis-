"""One-off: POST Mira job, poll, frame luminance check."""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:8765"
MSG = "create a quick teaser of crypto rafts"


def http_json(method: str, path: str, body: dict | None = None, timeout: float = 45) -> dict:
    data = None
    headers = {"Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(API + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def frame_check(mp4: Path, t: float = 1.0) -> tuple[float, bool, str]:
    import imageio_ffmpeg
    from PIL import Image
    import io

    out_dir = Path(__file__).resolve().parents[1] / "data" / "mira"
    jpg = out_dir / "_verify_frame.jpg"
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run(
        [ff, "-y", "-ss", str(t), "-i", str(mp4), "-frames:v", "1", "-q:v", "2", str(jpg)],
        capture_output=True,
        timeout=60,
    )
    if not jpg.is_file():
        return 0.0, False, "no frame extracted"
    im = Image.open(jpg).convert("RGB")
    im.thumbnail((400, 400))
    px = list(im.getdata())
    mean = sum((r + g + b) / 3 for r, g, b in px) / len(px)
    ok = mean >= 15
    # dominant color hint
    top = im.getpixel((im.size[0] // 2, im.size[1] // 2))
    desc = f"mean_lum={mean:.1f} center_rgb={top}"
    return mean, ok, desc


def main() -> int:
    t0 = time.time()
    start = http_json("POST", "/api/mira", {"message": MSG})
    print("start:", json.dumps(start)[:300], flush=True)
    deadline = t0 + 150
    last: dict = {}
    while time.time() < deadline:
        time.sleep(2.5)
        last = http_json("GET", "/api/mira-status", timeout=20)
        st = str(last.get("status") or last.get("state") or "")
        prog = last.get("progress") or last.get("message") or ""
        print(f"poll status={st!r} prog={str(prog)[:80]}", flush=True)
        if st in ("done", "ok", "error", "failed"):
            break
    elapsed = time.time() - t0
    video = (
        last.get("video_path")
        or last.get("video")
        or (last.get("result") or {}).get("video_path")
    )
    if not video:
        print(json.dumps(last, indent=2)[:2000])
        print(f"FAIL no video elapsed={elapsed:.1f}s")
        return 1
    p = Path(str(video))
    if not p.is_file():
        print(f"FAIL missing {p} elapsed={elapsed:.1f}s")
        return 1
    mean, ok, desc = frame_check(p)
    url = f"{API}/data/mira/videos/{p.name}" if "videos" in str(p) else str(p)
    print(f"elapsed={elapsed:.1f}s")
    print(f"video_path={p}")
    print(f"size={p.stat().st_size}")
    print(f"frame_ok={ok} {desc}")
    print(f"video_url={url}")
    return 0 if ok and p.stat().st_size > 50000 else 1


if __name__ == "__main__":
    sys.exit(main())
