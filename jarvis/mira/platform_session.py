"""Signed-in continuous platform tours — login, explore, KYC/KYB, no hard scene cuts.

One Playwright recording session covers the whole walkthrough so scene switches
never hitch. Voiceover is mixed onto the continuous video timeline.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)

# Per-platform auth + post-login exploration (any platform can add an entry).
# Each step may include "tags" for exclusion filtering (skip/without/don't show).
_AUTH: dict[str, dict[str, Any]] = {
    "cryptorafts": {
        "login_url": "https://cryptorafts.com/login",
        "home": "https://cryptorafts.com/",
        "signed_steps": (
            {
                "url": "https://cryptorafts.com/",
                "dwell_sec": 3.2,
                "scrolls": (0, 2000, 4500),
                "line": "CryptoRafts home — BUILD to CONNECT, plus Atlas AI risk scoring.",
                "action": "browse",
                "tags": ("home", "overview", "ai", "scoring"),
            },
            {
                "url": "https://cryptorafts.com/features",
                "dwell_sec": 3.5,
                "scrolls": (0, 2000, 4000),
                "line": "Features — role dashboards, deal rooms, RaftAI, and AI scoring credits.",
                "action": "browse",
                "tags": ("features", "roles", "ai", "raftai", "scoring", "deals"),
            },
            {
                "url": "https://cryptorafts.com/features",
                "dwell_sec": 3.0,
                "scrolls": (5000, 6500),
                "line": "MainHub on BSC and security partners on the Features page.",
                "action": "browse",
                "tags": ("features", "mainhub", "security"),
            },
            {
                "url": "https://cryptorafts.com/login",
                "dwell_sec": 2.0,
                "scrolls": (0,),
                "line": "Signing in so we can open the real product.",
                "action": "login",
                "tags": ("login", "signin", "auth"),
            },
            {
                "url": "https://cryptorafts.com/dashboard",
                "dwell_sec": 3.0,
                "scrolls": (0, 600),
                "line": "Dashboard — roles and projects in one command center.",
                "action": "browse",
                "tags": ("dashboard", "app"),
            },
            {
                "url": "https://cryptorafts.com/dealflow",
                "dwell_sec": 3.0,
                "scrolls": (0, 700),
                "line": "Dealflow — verified projects and connection targets.",
                "action": "browse",
                "tags": ("dealflow", "deals"),
            },
            {
                "url": "https://cryptorafts.com/kyc",
                "dwell_sec": 2.8,
                "scrolls": (0, 450),
                "line": "KYC and KYB — identity verification on screen.",
                "action": "kyc",
                "tags": ("kyc", "kyb", "verify"),
            },
            {
                "url": "https://cryptorafts.com/whitepaper",
                "dwell_sec": 3.0,
                "scrolls": (0, 1000),
                "line": "Whitepaper — verified identity, structured data, and on-chain credentials.",
                "action": "browse",
                "tags": ("whitepaper", "docs"),
            },
            {
                "url": "https://cryptorafts.com/news",
                "dwell_sec": 2.5,
                "scrolls": (0, 600),
                "line": "News — ChainGPT-powered crypto headlines inside CryptoRafts.",
                "action": "browse",
                "tags": ("news", "headlines"),
            },
        ),
    },
    "huggingface": {
        "login_url": "https://huggingface.co/login",
        "home": "https://huggingface.co",
        "signed_steps": (
            {
                "url": "https://huggingface.co",
                "dwell_sec": 2.0,
                "scrolls": (0, 600),
                "line": "Hugging Face home — then Jarvis signs in to open your hub.",
                "action": "browse",
            },
            {
                "url": "https://huggingface.co/login",
                "dwell_sec": 2.0,
                "scrolls": (0,),
                "line": "Signing in to Hugging Face with your saved credentials.",
                "action": "login",
            },
            {
                "url": "https://huggingface.co/models",
                "dwell_sec": 2.2,
                "scrolls": (0, 900),
                "line": "Signed-in Models — search, filter, and open model cards.",
                "action": "browse",
            },
        ),
    },
    "github": {
        "login_url": "https://github.com/login",
        "home": "https://github.com",
        "signed_steps": (
            {
                "url": "https://github.com",
                "dwell_sec": 2.0,
                "scrolls": (0, 500),
                "line": "GitHub home, then Jarvis signs in to your account.",
                "action": "browse",
            },
            {
                "url": "https://github.com/login",
                "dwell_sec": 2.0,
                "scrolls": (0,),
                "line": "Entering GitHub credentials for a signed-in product tour.",
                "action": "login",
            },
            {
                "url": "https://github.com",
                "dwell_sec": 2.2,
                "scrolls": (0, 800),
                "line": "Signed-in GitHub dashboard and repositories.",
                "action": "browse",
            },
        ),
    },
}


def auth_spec(platform_id: str) -> dict[str, Any] | None:
    return _AUTH.get(platform_id)


def _topic_exclusions(topic: str) -> set[str]:
    """Parse 'without X / don't show X / skip X / no X' into step tags to drop."""
    t = (topic or "").lower()
    found: set[str] = set()
    patterns = (
        r"(?:without|dont|don't|do\s+not|skip|except|exclude|no)\s+"
        r"(?:the\s+|any\s+|showing\s+|show\s+)?"
        r"([a-z0-9][a-z0-9\s\-]{1,32}?)(?=\s*(?:,|and|or|\.|$|but|just|only|please))"
    )
    for m in re.finditer(patterns, t):
        chunk = re.sub(r"[^a-z0-9\s\-]+", " ", m.group(1)).strip()
        for part in re.split(r"[\s\-]+", chunk):
            if len(part) >= 2:
                found.add(part)
    # Common aliases
    aliases = {
        "sign": "login",
        "signin": "login",
        "signing": "login",
        "log": "login",
        "auth": "login",
        "verification": "kyc",
        "verify": "kyc",
        "kyb": "kyc",
        "paper": "whitepaper",
        "score": "scoring",
        "scores": "scoring",
        "raft": "raftai",
    }
    out: set[str] = set()
    for x in found:
        out.add(aliases.get(x, x))
    return out


def _wants_full_coverage(topic: str) -> bool:
    """Full platform tour by default. Only shrink when Owner asks for a quick clip."""
    t = (topic or "").lower()
    if re.search(
        r"\b(quick|short|brief|teaser|preview|snippet|30\s*sec|15\s*sec|"
        r"highlights?\s+only)\b",
        t,
    ):
        return False
    return True


def _filter_steps_by_topic(steps: list[dict[str, Any]], topic: str) -> list[dict[str, Any]]:
    excl = _topic_exclusions(topic)
    if not excl:
        return steps
    kept: list[dict[str, Any]] = []
    for step in steps:
        tags = {str(x).lower() for x in (step.get("tags") or ())}
        action = str(step.get("action") or "").lower()
        url = str(step.get("url") or "").lower()
        line = str(step.get("line") or "").lower()
        blob = tags | {action} | set(re.findall(r"[a-z]{3,}", url + " " + line))
        if blob & excl:
            continue
        kept.append(step)
    return kept or steps


def _creds() -> tuple[str, str]:
    email = ""
    password = ""
    try:
        from jarvis.identity import browser_email, browser_password

        email = (browser_email() or "").strip()
        password = (browser_password() or "").strip()
    except Exception:
        pass
    if not email or not password:
        try:
            from jarvis.tools.credentials import get_user_email, get_user_password

            email = email or (get_user_email("") or "").strip()
            password = password or (get_user_password("") or "").strip()
        except Exception:
            pass
    return email, password


def _ffmpeg() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def _wait_ready(page: Any, *, max_wait_sec: float = 3.0) -> None:
    """Fast paint check — skip networkidle (that alone can cost 10s+ per page)."""
    try:
        page.wait_for_load_state("domcontentloaded", timeout=8_000)
    except Exception:
        pass
    deadline = time.time() + max(0.8, float(max_wait_sec))
    while time.time() < deadline:
        try:
            ok = page.evaluate(
                """() => {
                  const b = document.body;
                  if (!b) return false;
                  const t = (b.innerText || '').trim().length;
                  const n = b.querySelectorAll('a,button,input,h1,h2,p,nav,main,img,section').length;
                  return t > 50 || n > 10;
                }"""
            )
            if ok:
                try:
                    page.evaluate(
                        """() => {
                          if (document.body) {
                            document.body.style.opacity = '1';
                            document.body.style.transition = 'opacity 0.2s ease';
                          }
                        }"""
                    )
                except Exception:
                    pass
                page.wait_for_timeout(80)
                return
        except Exception:
            pass
        page.wait_for_timeout(100)


def _install_smooth_boot(context: Any) -> None:
    """Dark shell + fade-in so loads never flash white / look frozen blank."""
    try:
        # Reuse Mira's cookie killer + dark boot so continuous tours stay clean too
        from jarvis.mira.platforms import _install_dark_boot

        _install_dark_boot(context)
    except Exception:
        try:
            context.add_init_script(
                """
                (() => {
                  const boot = () => {
                    try {
                      document.documentElement.style.background = '#0b1220';
                      if (document.body) {
                        document.body.style.background = '#0b1220';
                        if (!document.body.dataset.miraFade) {
                          document.body.dataset.miraFade = '1';
                          document.body.style.opacity = '0';
                        }
                      }
                    } catch (e) {}
                  };
                  boot();
                  document.addEventListener('DOMContentLoaded', boot);
                })();
                """
            )
        except Exception:
            pass


def _goto_painted(page: Any, url: str, *, timeout_ms: int = 8_000) -> None:
    """Navigate and only continue once real UI is painted (avoids mid-tour blank hangs)."""
    try:
        cur = (page.url or "").split("#")[0].rstrip("/")
        tgt = url.split("#")[0].rstrip("/")
        if cur == tgt:
            _wait_ready(page, max_wait_sec=1.0)
            return
    except Exception:
        pass
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    except Exception:
        # Timeout / interrupted nav — soft retry; never leave a white hang
        try:
            page.goto(url, wait_until="commit", timeout=max(3_500, timeout_ms // 2))
        except Exception:
            pass
    _wait_ready(page, max_wait_sec=1.6)
    # Cookie / consent / ads banners block the recorded view — clear them
    try:
        from jarvis.mira.platforms import _dismiss_blocking_overlays

        _dismiss_blocking_overlays(page)
    except Exception:
        pass


def _smooth_scroll(page: Any, targets: list[int], dwell_sec: float) -> None:
    if not targets:
        targets = [500]
    per = max(0.25, float(dwell_sec) / max(1, len(targets)))
    prev = 0
    for y in targets:
        steps = max(2, min(4, abs(y - prev) // 220 or 2))
        for s in range(1, steps + 1):
            mid = int(prev + (y - prev) * (s / steps))
            try:
                page.evaluate(f"window.scrollTo(0, {mid})")
            except Exception:
                break
            page.wait_for_timeout(max(15, int((per * 1000) / steps)))
        prev = y


def _try_login(page: Any, email: str, password: str) -> list[str]:
    """Sign in via email/password OR Google/Apple SSO. Returns notes (never logs secrets)."""
    notes: list[str] = []
    if not email or not password:
        notes.append("login_skipped_no_credentials")
        return notes
    try:
        from jarvis.tools import api_hunter as ah

        try:
            ah._click_any(page, [r"accept", r"agree", r"allow", r"got it", r"ok"])
            page.wait_for_timeout(150)
        except Exception:
            pass

        body = ""
        try:
            body = (page.inner_text("body") or "").lower()
        except Exception:
            pass
        google_only = bool(
            re.search(r"email.?password.*(disabled|not available)|use google or apple", body)
            or re.search(r"continue with google", body)
        )

        if google_only or not ah._email_visible(page):
            notes.append("login_mode=google_sso")
            # Visual SSO only — full Google auth loops burn the tour budget
            # and freeze mid-video in headless. Cookies reuse storage_state.
            clicked = bool(ah._click_google_sso_button(page))
            notes.append(f"google_click={clicked}")
            page.wait_for_timeout(700)
            if clicked:
                notes.append("google_sso=visual_only")
            else:
                notes.append("google_sso=skipped")
            _wait_ready(page, max_wait_sec=1.2)
            return notes

        filled_e = bool(ah._fill_email(page, email))
        notes.append(f"login_email_filled={filled_e}")
        page.wait_for_timeout(200)
        try:
            ah._click_any(page, [r"continue", r"next", r"sign\s*in", r"log\s*in"])
            page.wait_for_timeout(350)
        except Exception:
            pass
        filled_p = bool(ah._fill_password(page, password))
        notes.append(f"login_password_filled={filled_p}")
        page.wait_for_timeout(150)
        clicked = bool(
            ah._click_any(
                page,
                [r"sign\s*in", r"log\s*in", r"continue", r"submit", r"next"],
            )
        )
        if not clicked:
            try:
                page.keyboard.press("Enter")
                clicked = True
            except Exception:
                pass
        notes.append(f"login_submit={clicked}")
        page.wait_for_timeout(500)
        _wait_ready(page, max_wait_sec=1.5)
    except Exception as exc:
        notes.append(f"login_error:{exc}")
        logger.warning("platform login failed: %s", exc)
    return notes


def _try_kyc_flow(page: Any) -> list[str]:
    """Advance KYC/KYB UI quickly — max 2 CTA clicks."""
    notes: list[str] = ["kyc_flow_start"]
    try:
        from jarvis.tools import api_hunter as ah

        for _ in range(1):
            clicked = ah._click_any(
                page,
                [
                    r"verify",
                    r"start\s*verification",
                    r"begin\s*kyc",
                    r"complete\s*kyc",
                    r"kyb",
                    r"kyc",
                    r"continue",
                    r"get\s*started",
                    r"next",
                ],
            )
            if not clicked:
                break
            notes.append("kyc_clicked_cta")
            page.wait_for_timeout(250)
            _wait_ready(page, max_wait_sec=0.8)
            _smooth_scroll(page, [0, 350], 0.45)

        try:
            if page.get_by_text(
                re.compile(r"upload.*(id|passport|license|document)|take a (photo|selfie)", re.I)
            ).first.is_visible(timeout=400):
                notes.append("kyc_needs_document_upload")
        except Exception:
            pass
    except Exception as exc:
        notes.append(f"kyc_error:{exc}")
    return notes


def _webm_to_mp4(src: Path, dest: Path) -> Path:
    ff = _ffmpeg()
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ff,
        "-y",
        "-ss",
        "1.2",
        "-i",
        str(src),
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-r",
        "24",
        "-an",
        str(dest),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    if proc.returncode != 0 or not dest.is_file() or dest.stat().st_size < 8000:
        cmd2 = [
            ff,
            "-y",
            "-i",
            str(src),
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "24",
            "-an",
            str(dest),
        ]
        proc2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=180)
        if proc2.returncode != 0 or not dest.is_file():
            raise RuntimeError((proc.stderr or proc2.stderr or "")[-400:])
    return dest.resolve()


def _probe(path: Path) -> float:
    ff = _ffmpeg()
    try:
        proc = subprocess.run(
            [ff, "-v", "error", "-err_detect", "ignore_err", "-i", str(path), "-f", "null", "-"],
            capture_output=True,
            text=True,
            timeout=12,
        )
        # Duration lives on stderr even with -v error sometimes; fall back to -i probe
        blob = (proc.stderr or "") + (proc.stdout or "")
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", blob)
        if m:
            return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    except Exception:
        pass
    try:
        proc = subprocess.run([ff, "-i", str(path)], capture_output=True, text=True, timeout=8)
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", proc.stderr or "")
        if m:
            return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    except Exception:
        pass
    return 1.0


def _concat_vos(vo_paths: list[Path], out_mp3: Path, *, gap_sec: float = 0.35) -> Path:
    """Concatenate chapter VO files with a short silence gap (smooth audio, no hard cut feel)."""
    ff = _ffmpeg()
    out_mp3.parent.mkdir(parents=True, exist_ok=True)
    if len(vo_paths) == 1:
        shutil.copy2(vo_paths[0], out_mp3)
        return out_mp3.resolve()
    work = out_mp3.parent / f"_vo_{uuid.uuid4().hex[:8]}"
    work.mkdir(parents=True, exist_ok=True)
    silence = work / "gap.mp3"
    subprocess.run(
        [ff, "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", f"{gap_sec:.2f}", "-q:a", "9", str(silence)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    lst = work / "list.txt"
    lines: list[str] = []
    for i, p in enumerate(vo_paths):
        lines.append(f"file '{p.resolve().as_posix()}'")
        if i + 1 < len(vo_paths) and silence.is_file():
            lines.append(f"file '{silence.resolve().as_posix()}'")
    lst.write_text("\n".join(lines) + "\n", encoding="utf-8")
    proc = subprocess.run(
        [ff, "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c:a", "libmp3lame", "-q:a", "4", str(out_mp3)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    shutil.rmtree(work, ignore_errors=True)
    if proc.returncode != 0 or not out_mp3.is_file():
        # Fallback: just use first VO
        shutil.copy2(vo_paths[0], out_mp3)
    return out_mp3.resolve()


def _salvage_webm(src: Path, dest: Path) -> Path:
    """Re-encode truncated Playwright webm into a playable mp4 (ignore container errors)."""
    ff = _ffmpeg()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not src.is_file() or src.stat().st_size < 8_000:
        raise RuntimeError(f"webm too small: {src} ({src.stat().st_size if src.is_file() else 0} bytes)")
    cmd = [
        ff,
        "-y",
        "-err_detect",
        "ignore_err",
        "-fflags",
        "+genpts+igndts+discardcorrupt",
        "-i",
        str(src),
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-vf",
        "fps=24",
        "-an",
        "-movflags",
        "+faststart",
        str(dest),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"salvage timeout after 120s size={src.stat().st_size}") from exc
    if proc.returncode != 0 or not dest.is_file() or dest.stat().st_size < 20_000:
        # Second try: copy timestamps from packet positions
        cmd2 = [
            ff,
            "-y",
            "-fflags",
            "+genpts+igndts+discardcorrupt",
            "-i",
            str(src),
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "26",
            "-pix_fmt",
            "yuv420p",
            "-vf",
            "fps=24",
            "-an",
            str(dest),
        ]
        proc2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=120)
        if proc2.returncode != 0 or not dest.is_file() or dest.stat().st_size < 20_000:
            raise RuntimeError((proc.stderr or proc2.stderr or "")[-400:])
    return dest.resolve()


def _mux_continuous(
    video: Path,
    audio: Path | None,
    out: Path,
    *,
    out_w: int,
    out_h: int,
    duration_hint: float | None = None,
) -> Path:
    """Fit continuous video + VO without chopping the visual tour short."""
    ff = _ffmpeg()
    out.parent.mkdir(parents=True, exist_ok=True)
    probed = _probe(video)
    unknown = probed < 3.0
    raw_dur = float(duration_hint) if unknown and duration_hint and duration_hint > 5 else probed
    # Cut blank browser boot — but never over-trim short captures
    if unknown:
        trim_start = 0.6
    elif raw_dur >= 40:
        trim_start = 2.0
    elif raw_dur >= 14:
        trim_start = 1.2
    elif raw_dur >= 8:
        trim_start = 0.6
    else:
        trim_start = min(0.4, max(0.1, raw_dur * 0.05))
    vdur = min(90.0, max(5.0, raw_dur - trim_start))
    adur = _probe(audio) if audio and audio.is_file() else 0.0
    stretch = 1.0
    if (not unknown) and adur > vdur + 0.5 and vdur > 1.0:
        stretch = min(1.35, adur / vdur)
    vf = (
        f"scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
        f"crop={out_w}:{out_h},fps=24"
    )
    if stretch > 1.02:
        vf = f"setpts={stretch:.4f}*PTS,{vf}"
    cmd = [ff, "-y", "-fflags", "+genpts+igndts", "-ss", f"{trim_start:.2f}", "-i", str(video)]
    if audio and audio.is_file():
        cmd += ["-i", str(audio)]
        if (not unknown) and vdur > adur + 0.4 and stretch <= 1.02:
            cmd += [
                "-filter_complex",
                f"[0:v]{vf}[v];[1:a]apad=whole_dur={vdur:.2f}[a]",
                "-map",
                "[v]",
                "-map",
                "[a]",
            ]
        else:
            cmd += ["-vf", vf, "-map", "0:v:0", "-map", "1:a:0"]
        cmd += [
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "23",
            "-r",
            "24",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-threads",
            "0",
            "-movflags",
            "+faststart",
        ]
        # Unknown-duration webm: encode all packets (no -t). Known: cap length.
        if unknown:
            cmd += ["-shortest", str(out)]
        else:
            cmd += ["-t", f"{vdur:.2f}", str(out)]
    else:
        cmd += [
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "23",
            "-r",
            "24",
            "-pix_fmt",
            "yuv420p",
            "-an",
            "-threads",
            "0",
            "-movflags",
            "+faststart",
        ]
        if not unknown:
            cmd += ["-t", f"{vdur:.2f}"]
        cmd += [str(out)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    if proc.returncode != 0 or not out.is_file():
        # Retry once with corrupt-packet forgiveness (Playwright webm often incomplete)
        soft = [
            ff,
            "-y",
            "-err_detect",
            "ignore_err",
            "-fflags",
            "+genpts+igndts+discardcorrupt",
            "-ss",
            f"{trim_start:.2f}",
            "-i",
            str(video),
        ]
        if audio and audio.is_file():
            soft += [
                "-i",
                str(audio),
                "-vf",
                vf,
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-crf",
                "23",
                "-r",
                "24",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-shortest",
                "-movflags",
                "+faststart",
                str(out),
            ]
        else:
            soft += [
                "-vf",
                vf,
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-crf",
                "23",
                "-r",
                "24",
                "-pix_fmt",
                "yuv420p",
                "-an",
                "-movflags",
                "+faststart",
                str(out),
            ]
        soft_proc = subprocess.run(soft, capture_output=True, text=True, timeout=90)
        if soft_proc.returncode != 0 or not out.is_file() or out.stat().st_size < 20_000:
            raise RuntimeError((proc.stderr or soft_proc.stderr or "")[-500:])
    return out.resolve()


def run_signed_continuous_tour(
    platform_id: str,
    platform_name: str,
    *,
    topic: str,
    aspect: str = "16:9",
    voice: str | None = None,
    audio_mode: str = "voice",
    out_root: Path | None = None,
    progress_cb: Any | None = None,
) -> dict[str, Any]:
    """One continuous screen-record: browse → sign in → explore → KYC/KYB → more pages."""
    from playwright.sync_api import sync_playwright

    notes: list[str] = ["mode=platform_signed_continuous_v1_fast"]
    t_wall = time.time()

    def _live(msg: str) -> None:
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass
        try:
            from jarvis.tools.mira_jobs import set_progress

            set_progress(msg)
        except Exception:
            pass
    spec = auth_spec(platform_id)
    if not spec:
        return {
            "ok": False,
            "status": "error",
            "message": f"No signed-in tour config for {platform_id}",
            "notes": notes,
        }

    email, password = _creds()
    can_login = bool(email and password)
    notes.append(f"credentials={'yes' if can_login else 'no'}")

    steps = list(spec.get("signed_steps") or [])
    if not steps:
        return {"ok": False, "status": "error", "message": "No signed steps", "notes": notes}

    full = _wants_full_coverage(topic)
    before = len(steps)
    steps = _filter_steps_by_topic(steps, topic)
    excl = _topic_exclusions(topic)
    if excl:
        notes.append(f"exclusions={sorted(excl)}")
        notes.append(f"steps_filtered={before}->{len(steps)}")
    notes.append(f"full_coverage={full}")
    # Never silently drop features — only a quick ask may trim
    if not full and len(steps) > 5:
        steps = steps[:5]
        notes.append("steps_quick_trim=5")
    else:
        notes.append(f"steps_unlimited={len(steps)}")

    vertical = aspect in ("9:16", "vertical", "shorts", "reel")
    width, height = (720, 1280) if vertical else (1280, 720)
    # Match record size — skip 1080p upscale (was burning 1–3 min on encode)
    out_w, out_h = width, height

    root = Path(out_root) if out_root else Path(__file__).resolve().parents[2] / "data" / "mira"
    clips_dir = root / "clips" / "platforms"
    audio_dir = root / "audio"
    videos_dir = root / "videos"
    work = clips_dir / f"_live_{uuid.uuid4().hex[:8]}"
    clips_dir.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)
    videos_dir.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)

    chapter_lines: list[str] = []
    chapter_urls: list[str] = []
    raw_videos: list[Path] = []
    record_sec = 40.0

    try:
        mira_profile = root / "chrome_profile"
        mira_profile.mkdir(parents=True, exist_ok=True)
        notes.append("chrome_profile=storage_state")

        pw = sync_playwright().start()
        try:
            ctx_kwargs: dict[str, Any] = {
                "viewport": {"width": width, "height": height},
                "record_video_dir": str(work),
                "record_video_size": {"width": width, "height": height},
                "user_agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
            }
            storage_path = mira_profile / "storage_state.json"
            if storage_path.is_file():
                ctx_kwargs["storage_state"] = str(storage_path)
                notes.append("storage_state=loaded")

            context = None
            used_persistent = False
            browser = None
            first_url = str(steps[0].get("url") or "").strip()
            # Headed HUD window was collapsing Playwright webm to ~8–9s on Windows.
            # Always record headless (reliable full-length); HUD still shows live progress text.
            live_hud = False
            try:
                from jarvis.tools.mira_jobs import is_running

                live_hud = bool(is_running())
            except Exception:
                live_hud = False
            _live(f"Launching browser on {platform_name}…")
            try:
                browser = pw.chromium.launch(
                    headless=True,
                    slow_mo=0,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-first-run",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                    ],
                )
                notes.append(
                    "browser=chromium_headless_record"
                    + ("_hud_progress" if live_hud else "_fast")
                )
            except Exception as exc:
                notes.append(f"headless_launch_fail:{exc}")
                raise

            # Warm first URL BEFORE recording starts (kills blank intro)
            try:
                warm_kwargs: dict[str, Any] = {
                    "viewport": {"width": width, "height": height},
                    "user_agent": ctx_kwargs["user_agent"],
                }
                if ctx_kwargs.get("storage_state"):
                    warm_kwargs["storage_state"] = ctx_kwargs["storage_state"]
                warm = browser.new_context(**warm_kwargs)
                wp = warm.new_page()
                if first_url:
                    wp.goto(first_url, wait_until="domcontentloaded", timeout=8_000)
                    _wait_ready(wp, max_wait_sec=1.0)
                warm.close()
                notes.append("warm_first_url=ok")
            except Exception as exc:
                notes.append(f"warm_first_url_fail:{exc}")

            # Start recording only after warm — first paint should be real UI
            context = browser.new_context(**ctx_kwargs)
            context.set_default_timeout(8_000)
            context.set_default_navigation_timeout(10_000)
            _install_smooth_boot(context)

            page = context.pages[0] if context.pages else context.new_page()
            notes.append("google_warm=skipped_for_speed")

            # Soft budget only warns — full tours keep going through every step
            t_browse = time.time()
            browse_budget = 180.0 if full else 55.0
            warned_budget = False

            for i, step in enumerate(steps):
                if (not warned_budget) and (time.time() - t_browse > browse_budget):
                    notes.append(f"time_budget_soft_warn_at_step={i}")
                    warned_budget = True
                    # Still continue — Owner asked for the whole platform
                url = str(step.get("url") or "").strip()
                action = str(step.get("action") or "browse").lower()
                line = str(step.get("line") or "").strip()
                scrolls = [int(x) for x in (step.get("scrolls") or (0, 500))]
                # Keep enough scroll samples for a real tour look (was over-trimmed to ~8s videos)
                if len(scrolls) > 4:
                    scrolls = [scrolls[0], scrolls[len(scrolls) // 3], scrolls[(2 * len(scrolls)) // 3], scrolls[-1]]
                base_dwell = float(step.get("dwell_sec") or 1.2)
                dwell = max(1.6, min(4.0, base_dwell * (1.8 if full else 1.2)))
                notes.append(f"live:{action}:{url}")
                chapter_lines.append(line or f"Exploring {platform_name}.")
                chapter_urls.append(url)
                short = (line or action or url)[:90]
                _live(f"On {platform_name}: {short}")
                try:
                    _goto_painted(page, url, timeout_ms=6_000)
                except Exception as exc:
                    notes.append(f"goto_fail:{i}:{exc}")
                    try:
                        _wait_ready(page, max_wait_sec=0.6)
                    except Exception:
                        pass
                    continue
                try:
                    from jarvis.tools import api_hunter as ah

                    ah._click_any(page, [r"accept", r"agree", r"allow all", r"got it"])
                except Exception:
                    pass
                if action == "login" and can_login:
                    _live(f"Signing in on {platform_name}…")
                    notes.extend(_try_login(page, email, password))
                    page.wait_for_timeout(100)
                    _smooth_scroll(page, [0, 120], 0.3)
                elif action == "kyc":
                    _live(f"KYC / verification on {platform_name}…")
                    notes.extend(_try_kyc_flow(page))
                    _smooth_scroll(page, scrolls, dwell)
                else:
                    _smooth_scroll(page, scrolls, dwell)

            # Persist cookies for next fast signed tour
            try:
                context.storage_state(path=str(storage_path))
                notes.append("storage_state=saved")
            except Exception as exc:
                notes.append(f"storage_state_save_fail:{exc}")

            # Let last frames paint, then CLOSE page and wait for Playwright to
            # finish writing the webm (killing early = corrupt file / mux fail).
            try:
                page.wait_for_timeout(500)
            except Exception:
                pass

            chromium_pid = None
            try:
                proc = getattr(browser, "process", None) if browser is not None else None
                if proc is not None:
                    chromium_pid = getattr(proc, "pid", None)
            except Exception:
                pass

            import threading

            video_handle = None
            try:
                video_handle = page.video
            except Exception:
                video_handle = None

            def _close_page() -> None:
                try:
                    page.close()
                except Exception:
                    pass

            closer_page = threading.Thread(target=_close_page, daemon=True)
            closer_page.start()
            closer_page.join(18.0)
            if closer_page.is_alive():
                notes.append("page_close_slow")

            raw_videos: list[Path] = []
            if video_handle is not None:
                try:
                    # May block briefly — already closed page, path should resolve
                    vp = Path(str(video_handle.path()))
                    if vp.is_file() and vp.stat().st_size > 80_000:
                        raw_videos = [vp]
                        notes.append("webm_via_page_video_path")
                except Exception as exc:
                    notes.append(f"video_path_fail:{exc}")

            if not raw_videos:
                found = sorted(work.glob("*.webm"), key=lambda p: p.stat().st_size, reverse=True)
                raw_videos = found[:1]

            if raw_videos:
                # Wait for file size to stop growing (Playwright may still flush)
                try:
                    target = raw_videos[0]
                    last = -1
                    for _ in range(12):
                        if not target.is_file():
                            break
                        sz = target.stat().st_size
                        if sz > 80_000 and sz == last:
                            break
                        last = sz
                        time.sleep(0.4)
                    notes.append(f"webm_stable_bytes={last}")
                except Exception as exc:
                    notes.append(f"webm_stable_fail:{exc}")
                notes.append(f"webm_bytes={raw_videos[0].stat().st_size}")
                safe = clips_dir / f"live_{platform_id}_{uuid.uuid4().hex[:6]}.webm"
                try:
                    shutil.copy2(raw_videos[0], safe)
                    raw_videos = [safe]
                    notes.append("webm_copied_after_close")
                except Exception as exc:
                    notes.append(f"webm_copy_fail:{exc}")

            def _close_browser() -> None:
                try:
                    if context is not None:
                        context.close()
                except Exception:
                    pass
                try:
                    if browser is not None:
                        browser.close()
                except Exception:
                    pass

            closer = threading.Thread(target=_close_browser, daemon=True)
            closer.start()
            # Never force-kill if we already copied a usable webm — kill corrupts the file
            join_sec = 4.0 if (raw_videos and raw_videos[0].is_file() and raw_videos[0].stat().st_size > 200_000) else 10.0
            closer.join(join_sec)
            if closer.is_alive():
                notes.append("browser_close_slow")
                if not raw_videos or not raw_videos[0].is_file() or raw_videos[0].stat().st_size < 200_000:
                    notes.append("browser_close_forced")
                    if chromium_pid:
                        try:
                            import os

                            os.kill(int(chromium_pid), 9)
                        except Exception:
                            pass
                else:
                    notes.append("skip_force_kill_have_webm")

            notes.append(f"persistent={used_persistent}")
            record_sec = max(8.0, time.time() - t_browse)
            notes.append(f"browse_wall={round(time.time() - t_wall, 1)}")
            notes.append(f"record_sec={round(record_sec, 1)}")
        finally:
            # Timed playwright stop — default stop hangs after forced browser kill
            import threading

            def _stop_pw() -> None:
                try:
                    pw.stop()
                except Exception:
                    pass

            stopper = threading.Thread(target=_stop_pw, daemon=True)
            stopper.start()
            stopper.join(2.0)
            if stopper.is_alive():
                notes.append("playwright_stop_timeout")
    except Exception as exc:
        shutil.rmtree(work, ignore_errors=True)
        return {
            "ok": False,
            "status": "error",
            "message": f"Signed tour failed: {exc}"[:240],
            "notes": notes,
            "platform": platform_id,
        }

    if not raw_videos:
        shutil.rmtree(work, ignore_errors=True)
        return {
            "ok": False,
            "status": "error",
            "message": "No continuous recording produced",
            "notes": notes,
            "platform": platform_id,
        }

    raw = raw_videos[0]
    continuous = raw
    # Always re-encode Playwright webm first — direct mux hangs/probes fail on truncated files
    salvage = clips_dir / f"salvage_{platform_id}_{uuid.uuid4().hex[:6]}.mp4"
    try:
        _live(f"Encoding {platform_name} screen recording…")
        continuous = _salvage_webm(raw, salvage)
        notes.append(f"webm_salvaged_bytes={continuous.stat().st_size}")
        salv_dur = _probe(continuous)
        notes.append(f"salvage_dur={round(salv_dur, 1)}")
        notes.append("encode=salvage_first")
        # Continuous Playwright webm on Windows often collapses long tours to ~10–20s.
        # Require real length; otherwise fall through to live page-by-page clips.
        min_ok = 40.0 if full else 22.0
        if salv_dur < min_ok:
            keep = clips_dir / f"short_{platform_id}_{uuid.uuid4().hex[:6]}.webm"
            try:
                shutil.copy2(raw, keep)
                notes.append(f"kept_short_webm={keep.name}")
            except Exception:
                pass
            return {
                "ok": False,
                "status": "error",
                "message": (
                    f"Live {platform_name} continuous capture too short "
                    f"({salv_dur:.0f}s, need ≥{min_ok:.0f}s). "
                    "Falling back to page-by-page live record."
                )[:240],
                "notes": notes,
                "platform": platform_id,
            }
    except Exception as exc:
        notes.append(f"salvage_first_fail:{exc}")
        # Keep trying with raw webm + soft mux below
        continuous = raw
        notes.append("encode=raw_webm_fallback")

    _live(f"Mixing voiceover + encoding {platform_name} tour…")

    mode = (audio_mode or "voice").strip().lower()
    audio_path: Path | None = None
    if mode in ("voice", "both") and chapter_lines and (time.time() - t_wall) < 95:
        try:
            from jarvis.mira.pipeline import _stem
            import sys

            joined = " ".join(chapter_lines[:10] if full else chapter_lines[:6])
            audio_path = audio_dir / f"{_stem(f'{platform_id}_live_mix', 'vo')}.mp3"
            # Isolated process — Playwright can leave an asyncio loop that breaks edge-tts
            vo_script = (
                "from jarvis.mira.pipeline import generate_voiceover\n"
                f"generate_voiceover({joined!r}, r'{audio_path.as_posix()}', voice={voice!r})\n"
            )
            vo_proc = subprocess.run(
                [sys.executable, "-c", vo_script],
                cwd=str(Path(__file__).resolve().parents[2]),
                capture_output=True,
                text=True,
                timeout=28,
            )
            if vo_proc.returncode == 0 and audio_path.is_file() and audio_path.stat().st_size > 400:
                notes.append("vo=single_pass")
            else:
                audio_path = None
                notes.append(f"vo_fail:{(vo_proc.stderr or vo_proc.stdout or '')[-160:]}")
        except Exception as exc:
            audio_path = None
            notes.append(f"vo_mix_fail:{exc}")
    elif mode in ("voice", "both"):
        notes.append("vo=skipped_budget")

    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_path = videos_dir / f"vid_{platform_id}_live_{stamp}_{uuid.uuid4().hex[:6]}.mp4"

    try:
        video_path = _mux_continuous(
            continuous,
            audio_path,
            out_path,
            out_w=out_w,
            out_h=out_h,
            duration_hint=record_sec,
        )
    except Exception as exc:
        # Keep raw recording for retry/debug — do not invent stock scenes
        keep = clips_dir / f"failed_{platform_id}_{uuid.uuid4().hex[:6]}{raw.suffix}"
        try:
            shutil.copy2(raw, keep)
            notes.append(f"kept_failed_webm={keep.name}")
        except Exception:
            pass
        return {
            "ok": False,
            "status": "error",
            "message": f"Mux failed: {exc}"[:240],
            "notes": notes,
            "platform": platform_id,
        }

    try:
        raw.unlink(missing_ok=True)
    except Exception:
        pass
    try:
        if salvage.is_file() and salvage.resolve() != Path(video_path).resolve():
            salvage.unlink(missing_ok=True)
    except Exception:
        pass
    shutil.rmtree(work, ignore_errors=True)

    notes.append(f"wall_sec={round(time.time() - t_wall, 1)}")

    script = " ".join(chapter_lines).strip() or topic
    beats = [
        {
            "tag": f"live{i}",
            "kind": "platform",
            "source": "platform_record",
            "visual": str(video_path),
            "audio": str(audio_path) if audio_path else "",
            "line": line,
            "heading": "",
            "query": platform_id,
            "platform_url": chapter_urls[i] if i < len(chapter_urls) else "",
        }
        for i, line in enumerate(chapter_lines)
    ]

    return {
        "ok": True,
        "status": "ok",
        "action": "create_video",
        "topic": topic,
        "script": script,
        "video_path": str(video_path),
        "duration_sec": int(_probe(video_path)),
        "aspect": aspect,
        "audio_mode": mode,
        "provider": "mira_platform_signed_continuous",
        "still_source": "platform_record",
        "platform": platform_id,
        "platform_name": platform_name,
        "signed_in": can_login,
        "beats": beats,
        "mira_engine": True,
        "is_trained_foundation_model": False,
        "message": (
            f"Signed-in continuous tour ready: {platform_name} "
            f"({len(chapter_lines)} chapters · {video_path.name})"
        ),
        "notes": notes,
        "learning_note": "Continuous signed-in recording — rate with mira_rate.",
    }


def enrich_generic_auth(platform_id: str, home: str, login_guess: str | None = None) -> None:
    """Register a minimal signed tour for a platform discovered at runtime."""
    if platform_id in _AUTH:
        return
    login = login_guess or urljoin(home.rstrip("/") + "/", "login")
    _AUTH[platform_id] = {
        "login_url": login,
        "home": home,
        "signed_steps": (
            {
                "url": home,
                "dwell_sec": 1.2,
                "scrolls": (0, 700),
                "line": f"Opening {platform_id} — Jarvis will sign in and explore the product.",
                "action": "browse",
                "tags": ("home", "overview"),
            },
            {
                "url": login,
                "dwell_sec": 1.0,
                "scrolls": (0,),
                "line": f"Signing in to {platform_id} with your saved Jarvis credentials.",
                "action": "login",
                "tags": ("login", "signin", "auth"),
            },
            {
                "url": home,
                "dwell_sec": 1.5,
                "scrolls": (0, 900),
                "line": f"Signed-in {platform_id} — exploring the product after login.",
                "action": "browse",
                "tags": ("app", "dashboard"),
            },
        ),
    }
