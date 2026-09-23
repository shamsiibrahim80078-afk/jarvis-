"""Direct platform tour smoke + frame luminance."""
import subprocess
import sys
import time
from pathlib import Path

import imageio_ffmpeg


def frame_check(mp4: Path, t: float = 1.0) -> tuple[float, bool, str]:
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
        return 0.0, False, "no frame"
    im = Image.open(jpg).convert("RGB")
    im.thumbnail((400, 400))
    px = list(im.getdata())
    lums = [(r + g + b) / 3 for r, g, b in px]
    spreads = [max(p) - min(p) for p in px]
    mean = sum(lums) / len(lums)
    spread = sum(spreads) / len(spreads)
    center = im.getpixel((im.size[0] // 2, im.size[1] // 2))
    ok = True
    if mean < 6 or (mean > 248 and spread < 10) or (mean < 22 and spread < 14):
        ok = False
    return mean, ok, f"mean_lum={mean:.1f} spread={spread:.1f} center_rgb={center}"


def main() -> int:
    topic = sys.argv[1] if len(sys.argv) > 1 else "create a quick teaser of crypto rafts"
    t0 = time.time()
    from jarvis.mira.platforms import run_platform_tour

    r = run_platform_tour(topic, audio_mode="mute")
    elapsed = time.time() - t0
    print("ok=", r.get("ok"), "status=", r.get("status"))
    print("notes=", (r.get("notes") or [])[-8:])
    vp = r.get("video_path")
    if not vp:
        print("message:", r.get("message"))
        print(f"elapsed={elapsed:.1f}s")
        return 1
    p = Path(vp)
    mean, ok, desc = frame_check(p)
    print(f"elapsed={elapsed:.1f}s")
    print(f"video_path={p}")
    print(f"size={p.stat().st_size}")
    print(f"frame_ok={ok} {desc}")
    return 0 if ok and p.stat().st_size > 50000 else 1


if __name__ == "__main__":
    sys.exit(main())
