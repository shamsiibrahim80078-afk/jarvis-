"""Autonomous API key hunter — sign in, grab keys, Chrome stays open until done."""

from __future__ import annotations

import logging
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

from jarvis.tools.api_registry import get_key, save_key, write_key_to_env
from jarvis.tools.command_parse import normalize
from jarvis.tools.credentials import get_user_email, get_user_password, mask_secret
from jarvis.tools.hunt_bus import set_done, set_failed, set_progress, set_running


def _env_hint(provider_id: str) -> str:
    return f"Say 'save {provider_id} api to .env' if you want it written to your environment."


def _format_key_result(name: str, key: str, env_key: str, write_env: bool) -> str:
    if write_env and env_key:
        return f"Got your {name} API key, sir:\n\n{key}\n\nSaved to .env as {env_key}."
    return f"Got your {name} API key, sir:\n\n{key}\n\n{_env_hint(name.lower())}"

logger = logging.getLogger("jarvis.api_hunter")

ROOT = Path(__file__).resolve().parents[2]
CHROME_PROFILE = ROOT / "data" / "chrome_profile"
LOG_PATH = ROOT / "data" / "hunt_worker.log"

_BROWSER_HOLD: list = []

PROVIDERS: dict[str, dict] = {
    "groq": {
        "names": ("groq", "grok"),
        "login": "https://console.groq.com/login",
        "keys": "https://console.groq.com/keys",
        "pattern": r"gsk_[A-Za-z0-9]{20,}",
        "env_key": "GROQ_API_KEY",
        "google_sso": True,
    },
    "fish": {
        "names": ("fish audio", "fishaudio", "fish"),
        "login": "https://fish.audio/auth/signin",
        "keys": "https://fish.audio/developers/",
        "pattern": r"sk-[A-Za-z0-9_-]{20,}",
        "env_key": "FISH_AUDIO_API_KEY",
    },
    "openrouter": {
        "names": ("openrouter", "open router"),
        "login": "https://openrouter.ai/sign-in",
        "keys": "https://openrouter.ai/keys",
        "pattern": r"sk-or-[A-Za-z0-9_-]{20,}",
        "env_key": "OPENROUTER_API_KEY",
        "google_sso": True,
    },
    "nvidia": {
        "names": ("nvidia", "nvidia nim", "nim"),
        "login": "https://build.nvidia.com/",
        "keys": "https://org.ngc.nvidia.com/setup/api-key",
        "pattern": r"nvapi-[A-Za-z0-9_-]{20,}",
        "env_key": "NVIDIA_API_KEY",
    },
    "elevenlabs": {
        "names": ("elevenlabs", "eleven labs", "eleven lab", "11labs", "11 labs", "11 lab"),
        "login": "https://elevenlabs.io/sign-in",
        "keys": "https://elevenlabs.io/app/settings/api-keys",
        "pattern": r"sk_[a-f0-9]{20,}",
        "env_key": "ELEVENLABS_API_KEY",
        "google_sso": True,
    },
    "gemini": {
        "names": ("gemini", "google ai", "google gemini"),
        "login": "https://aistudio.google.com/",
        "keys": "https://aistudio.google.com/apikey",
        "pattern": r"AIza[A-Za-z0-9_-]{30,}",
        "env_key": "GEMINI_API_KEY",
        "google_sso": True,
    },
    "anthropic": {
        "names": ("anthropic", "claude", "claude ai"),
        "login": "https://console.anthropic.com/login",
        "keys": "https://console.anthropic.com/settings/keys",
        "pattern": r"sk-ant-[A-Za-z0-9_-]{20,}",
        "env_key": "ANTHROPIC_API_KEY",
        "google_sso": True,
    },
    "openai": {
        "names": ("openai", "chatgpt", "chat gpt", "gpt"),
        "login": "https://platform.openai.com/login",
        "keys": "https://platform.openai.com/api-keys",
        "pattern": r"sk-[A-Za-z0-9]{20,}",
        "env_key": "OPENAI_API_KEY",
        "google_sso": True,
    },
    "together": {
        "names": ("together", "together ai", "togetherai"),
        "login": "https://api.together.xyz/signin",
        "keys": "https://api.together.xyz/settings/api-keys",
        "pattern": r"[A-Za-z0-9]{32,}",
        "env_key": "TOGETHER_API_KEY",
        "google_sso": True,
    },
    "huggingface": {
        "names": ("huggingface", "hugging face", "hf"),
        "login": "https://huggingface.co/login",
        "keys": "https://huggingface.co/settings/tokens",
        "pattern": r"hf_[A-Za-z0-9]{20,}",
        "env_key": "HUGGINGFACE_API_KEY",
    },
    "deepseek": {
        "names": ("deepseek", "deep seek"),
        "login": "https://platform.deepseek.com/login",
        "keys": "https://platform.deepseek.com/api_keys",
        "pattern": r"sk-[A-Za-z0-9]{20,}",
        "env_key": "DEEPSEEK_API_KEY",
    },
    "fireworks": {
        "names": ("fireworks", "fireworks ai"),
        "login": "https://fireworks.ai/login",
        "keys": "https://fireworks.ai/account/api-keys",
        "pattern": r"fw_[A-Za-z0-9]{20,}",
        "env_key": "FIREWORKS_API_KEY",
        "google_sso": True,
    },
    "mistral": {
        "names": ("mistral", "mistral ai"),
        "login": "https://console.mistral.ai/home",
        "keys": "https://console.mistral.ai/api-keys",
        "pattern": r"[A-Za-z0-9]{32,}",
        "env_key": "MISTRAL_API_KEY",
        "google_sso": True,
    },
    "cohere": {
        "names": ("cohere",),
        "login": "https://dashboard.cohere.com/welcome/login",
        "keys": "https://dashboard.cohere.com/api-keys",
        "pattern": r"[A-Za-z0-9_-]{30,}",
        "env_key": "COHERE_API_KEY",
        "google_sso": True,
    },
    "cerebras": {
        "names": ("cerebras",),
        "login": "https://cloud.cerebras.ai/",
        "keys": "https://cloud.cerebras.ai/?_redirect=api-keys",
        "pattern": r"csk-[A-Za-z0-9_-]{20,}",
        "env_key": "CEREBRAS_API_KEY",
        "google_sso": True,
    },
}

# ── Logging ──────────────────────────────────────────────

def _hunt_log(msg: str) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass
    logger.info(msg)

# ── Browser hold ─────────────────────────────────────────

def _hold_browser(*objs) -> None:
    global _BROWSER_HOLD
    _BROWSER_HOLD = list(objs)


def _release_browser() -> None:
    global _BROWSER_HOLD
    held = list(_BROWSER_HOLD)
    _BROWSER_HOLD = []
    for obj in reversed(held):
        try:
            if hasattr(obj, "__exit__"):
                obj.__exit__(None, None, None)
            elif hasattr(obj, "stop"):
                obj.stop()
            elif hasattr(obj, "close"):
                obj.close()
        except Exception:
            pass


def _unlock_chrome_profile(*, kill: bool = False) -> None:
    """Clear Singleton locks. Optionally kill hung Chrome using our profile.

    Never kill mid-hunt — that closes the live Playwright context.
    """
    import subprocess

    if kill:
        profile = str(CHROME_PROFILE.resolve())
        try:
            ps = (
                "Get-CimInstance Win32_Process -Filter \"Name = 'chrome.exe' OR Name = 'chromium.exe'\" | "
                f"Where-Object {{ $_.CommandLine -like '*chrome_profile*' }} | "
                "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True,
                text=True,
                timeout=25,
            )
            _hunt_log("Killed hung Chrome profile processes")
        except Exception as exc:
            _hunt_log(f"Chrome unlock kill skipped: {exc}")
        time.sleep(1.2)
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile"):
        try:
            p = CHROME_PROFILE / name
            if p.exists():
                p.unlink(missing_ok=True)
        except Exception:
            pass


def _launch_persistent(pw, *, channel: str | None = "chrome"):
    """Launch persistent Chrome; recover if profile already in use."""
    kwargs: dict = dict(
        headless=False,
        slow_mo=80,
        viewport={"width": 1280, "height": 900},
        args=[
            "--disable-blink-features=AutomationControlled",
            "--start-maximized",
            "--no-first-run",
        ],
    )
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            if channel:
                return pw.chromium.launch_persistent_context(
                    str(CHROME_PROFILE), channel=channel, **kwargs
                )
            return pw.chromium.launch_persistent_context(str(CHROME_PROFILE), **kwargs)
        except Exception as exc:
            last_exc = exc
            msg = str(exc).lower()
            if "already in use" in msg or "existing browser session" in msg or "singleton" in msg:
                _hunt_log(f"Chrome profile locked (attempt {attempt + 1}) — waiting")
                # Prefer wait over kill — killing closes a live hunt mid-flight
                time.sleep(2.5 + attempt * 1.5)
                if attempt >= 1:
                    _unlock_chrome_profile(kill=False)
                if attempt >= 2:
                    _hunt_log("Still locked — force unlock")
                    _unlock_chrome_profile(kill=True)
                channel = None if attempt >= 1 else channel
                continue
            if channel:
                _hunt_log(f"Chrome channel launch failed — retry without channel: {exc}")
                channel = None
                continue
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError("Chrome launch failed")

# ── Provider detection ───────────────────────────────────

def detect_provider(text: str) -> str | None:
    lower = normalize(text)
    if re.search(r"\b11\s*labs?\b", lower) or re.search(r"\beleven\s*labs?\b", lower):
        return "elevenlabs"
    candidates: list[tuple[int, str, str]] = []
    for pid, cfg in PROVIDERS.items():
        for name in cfg["names"]:
            n = name.lower().strip()
            if n:
                candidates.append((len(n), n, pid))
    candidates.sort(reverse=True)
    for _, n, pid in candidates:
        # Word boundary: "groq" matches "groq cloud", not "ngrok"
        if re.search(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])", lower):
            return pid
        # Glued brand: GroqCloud / openai-api — only at start of a token
        if re.search(rf"(?<![a-z0-9]){re.escape(n)}(?=[a-z0-9]{{2,}})", lower) and len(n) >= 4:
            return pid
    return None


def detect_provider_from_url(url: str) -> str | None:
    """Match a raw URL to a known provider."""
    domain = urlparse(url).netloc.lower().replace("www.", "")
    for pid, cfg in PROVIDERS.items():
        login_domain = urlparse(cfg["login"]).netloc.lower().replace("www.", "")
        keys_domain = urlparse(cfg["keys"]).netloc.lower().replace("www.", "")
        if domain == login_domain or domain == keys_domain:
            return pid
        for name in cfg["names"]:
            token = name.replace(" ", "").lower()
            if token and token in domain and token != "ai":
                return pid
    return None


def fuzzy_match_provider(name: str) -> str | None:
    lower = re.sub(r"\s+", " ", name.lower().strip())
    lower = re.sub(r"\b(api|key|keys|the|ai|service|platform)\b", "", lower).strip()
    if not lower:
        return None
    pid = detect_provider(lower)
    if pid:
        return pid
    for pid, cfg in PROVIDERS.items():
        for n in cfg["names"]:
            n = n.lower().strip()
            if not n:
                continue
            if lower == n:
                return pid
            if re.search(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])", lower):
                return pid
    return None


def ensure_provider(name: str) -> str:
    pid = fuzzy_match_provider(name)
    if pid:
        return pid
    slug = re.sub(r"[^a-z0-9]", "", name.lower())[:32] or "custom"
    if slug in PROVIDERS:
        return slug
    domain = re.sub(r"[^a-z0-9]", "", name.lower()) or slug
    PROVIDERS[slug] = {
        "names": (name.lower(), slug, domain),
        "login": f"https://{domain}.com/login",
        "keys": f"https://{domain}.com/settings/api-keys",
        "pattern": r"(?:sk-[A-Za-z0-9_-]{20,}|gsk_[A-Za-z0-9]{20,}|sk_[a-f0-9]{20,}|hf_[A-Za-z0-9]{20,}|AIza[A-Za-z0-9_-]{30,})",
        "env_key": f"{slug.upper()}_API_KEY",
        "dynamic": True,
    }
    return slug

# ── Playwright helpers ───────────────────────────────────

def _has_playwright() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def _safe_wait(page, ms: int = 1000) -> None:
    try:
        page.wait_for_timeout(ms)
    except Exception:
        time.sleep(ms / 1000)


EMAIL_SELECTORS = [
    # Google account identifier (must be first)
    "#identifierId",
    'input[name="identifier"]',
    'input[type="email"]',
    'input[name="email"]',
    'input[autocomplete="email"]',
    'input[autocomplete="username"]',
    'input[placeholder*="mail" i]',
    'input[placeholder*="Email" i]',
    'input[id*="email" i]',
    'input[id*="identifier" i]',
    "#email", "#identifier",
]

PASSWORD_SELECTORS = [
    'input[type="password"]',
    'input[name="password"]',
    'input[name="Passwd"]',
    'input[autocomplete="current-password"]',
    'input[autocomplete="new-password"]',
    'input[placeholder*="assword" i]',
    'input[id*="password" i]',
    "#password",
    "#Passwd",
]


def _fill_typed(page, selectors: list[str], value: str, kind: str) -> bool:
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if not loc.is_visible(timeout=2500):
                continue
            try:
                inp_type = (loc.get_attribute("type") or "").lower()
                name_attr = (loc.get_attribute("name") or "").lower()
                auto = (loc.get_attribute("autocomplete") or "").lower()
                el_id = (loc.get_attribute("id") or "").lower()
                if kind == "email":
                    if inp_type == "password":
                        continue
                    email_typed = inp_type == "email"
                    email_named = any(
                        x in name_attr or x in auto or x in el_id
                        for x in ("email", "identifier", "username")
                    )
                    if inp_type and inp_type not in ("email", "text") and not email_named:
                        continue
                    if (
                        not email_typed
                        and not email_named
                        and "email" not in sel.lower()
                        and "identifier" not in sel.lower()
                    ):
                        continue
                if kind == "password" and (inp_type == "email" or "email" in name_attr or "mail" in auto):
                    continue
            except Exception:
                pass
            try:
                current = (loc.input_value(timeout=1500) or "").strip()
                if current and (
                    current == value
                    or (kind == "email" and current.lower() == value.lower())
                ):
                    preview = value if kind == "email" else "********"
                    _hunt_log(f"SKIP {kind} already filled via {sel} = {preview}")
                    return True
            except Exception:
                pass
            loc.click(timeout=3000)
            try:
                existing = (loc.input_value(timeout=800) or "").strip()
            except Exception:
                existing = ""
            if existing:
                try:
                    loc.fill("", timeout=2000)
                except Exception:
                    loc.press("Control+A")
                    loc.press("Backspace")
            # Google/React often ignores fill() — type character by character
            filled_ok = False
            try:
                loc.fill(value, timeout=8000)
                current = (loc.input_value(timeout=1500) or "").strip()
                if current == value or (kind == "email" and current.lower() == value.lower()) or value in current:
                    filled_ok = True
            except Exception:
                pass
            if not filled_ok:
                try:
                    loc.click(timeout=2000)
                    loc.press("Control+A")
                    loc.press("Backspace")
                    loc.press_sequentially(value, delay=25)
                    current = (loc.input_value(timeout=1500) or "").strip()
                    if current == value or (kind == "email" and current.lower() == value.lower()) or value in current:
                        filled_ok = True
                except Exception:
                    try:
                        page.keyboard.type(value, delay=25)
                        filled_ok = True
                    except Exception:
                        pass
            if filled_ok:
                preview = value if kind == "email" else "********"
                _hunt_log(f"OK filled {kind} via {sel} = {preview}")
                return True
            _hunt_log(f"WARN fill mismatch {kind} via {sel}")
        except Exception:
            continue

    labels = (
        ("Email", "E-mail", "email address", "Username", "Email or phone")
        if kind == "email"
        else ("Password", "Current password", "Your password", "Enter your password")
    )
    for label in labels:
        try:
            loc = page.get_by_label(re.compile(rf"{re.escape(label)}", re.I)).first
            if loc.is_visible(timeout=1200):
                if kind == "email" and (loc.get_attribute("type") or "").lower() == "password":
                    continue
                loc.click(timeout=2000)
                try:
                    loc.fill("", timeout=1500)
                except Exception:
                    pass
                try:
                    loc.fill(value, timeout=5000)
                except Exception:
                    loc.press_sequentially(value, delay=25)
                _hunt_log(f"OK filled {kind} via label {label}")
                return True
        except Exception:
            continue

    if kind == "email":
        try:
            page.get_by_placeholder(re.compile(r"mail|user|phone", re.I)).first.fill(value, timeout=4000)
            _hunt_log("OK filled email via placeholder")
            return True
        except Exception:
            pass
    _hunt_log(f"FAIL could not fill {kind} field")
    return False


_SSO_LABEL = re.compile(r"google|apple|github|facebook|microsoft|passkey|\bsso\b", re.I)
_LAST_HUNT_NOTE = ""


def _progress(msg: str) -> None:
    _hunt_log(msg)
    try:
        set_progress(msg)
    except Exception:
        pass


def _field_visible(page, selectors: list[str]) -> bool:
    for sel in selectors:
        try:
            if page.locator(sel).first.is_visible(timeout=500):
                return True
        except Exception:
            continue
    return False


def _password_visible(page) -> bool:
    return _field_visible(page, PASSWORD_SELECTORS)


def _email_visible(page) -> bool:
    return _field_visible(page, EMAIL_SELECTORS)


def _email_field_value(page) -> str:
    for sel in EMAIL_SELECTORS:
        try:
            loc = page.locator(sel).first
            if not loc.is_visible(timeout=400):
                continue
            if (loc.get_attribute("type") or "").lower() == "password":
                continue
            return (loc.input_value(timeout=800) or "").strip()
        except Exception:
            continue
    return ""


def _email_already_filled(page, email: str) -> bool:
    current = _email_field_value(page)
    return bool(current) and current.lower() == (email or "").strip().lower()


def _captcha_visible(page) -> bool:
    for sel in (
        'iframe[src*="recaptcha"]',
        'iframe[src*="hcaptcha"]',
        'iframe[title*="captcha" i]',
    ):
        try:
            if page.locator(sel).first.is_visible(timeout=400):
                return True
        except Exception:
            continue
    try:
        if page.get_by_text(re.compile(r"verify you are (a )?human|i am not a robot", re.I)).first.is_visible(timeout=400):
            return True
    except Exception:
        pass
    return False


def _fill_email(page, email: str) -> bool:
    # Prefer email even if a password field is also on the page
    if not _email_visible(page):
        if _password_visible(page):
            _hunt_log("On password step — not filling email")
            return False
        _hunt_log("Email field not visible — skip fill")
        return False
    if _email_already_filled(page, email):
        _hunt_log("Email already correct — skip fill")
        return True
    return _fill_typed(page, EMAIL_SELECTORS, email, "email")


def _needs_email_before_password(page, email: str) -> bool:
    """True when we must fill email before touching the password field."""
    # Password challenge: never insist on email again
    if _google_on_password_step(page) or (
        _password_visible(page) and not _google_on_identifier_step(page)
    ):
        return False
    if _google_on_account_chooser(page):
        return False
    if _email_visible(page) and not _email_already_filled(page, email):
        return True
    url = _google_url(page)
    if "identifier" in url and not _email_already_filled(page, email):
        return True
    return False


def _fill_password(page, password: str) -> bool:
    if not _password_visible(page):
        _hunt_log("No password field visible — refusing to type password")
        return False
    # Prefer sequential typing for special characters (e.g. . @ !)
    for sel in PASSWORD_SELECTORS:
        try:
            loc = page.locator(sel).first
            if not loc.is_visible(timeout=2000):
                continue
            if (loc.get_attribute("type") or "").lower() not in ("password", ""):
                # still allow name=password
                name_attr = (loc.get_attribute("name") or "").lower()
                if "password" not in name_attr and "password" not in sel.lower():
                    continue
            loc.click(timeout=3000)
            try:
                loc.fill("", timeout=1500)
            except Exception:
                try:
                    loc.press("Control+A")
                    loc.press("Backspace")
                except Exception:
                    pass
            loc.press_sequentially(password, delay=30)
            _hunt_log(f"OK filled password via {sel} (typed)")
            return True
        except Exception:
            continue
    return _fill_typed(page, PASSWORD_SELECTORS, password, "password")


def _click_any(page, patterns: list[str]) -> bool:
    for pat in patterns:
        try:
            btn = page.get_by_role("button", name=re.compile(pat, re.I)).first
            if btn.is_visible(timeout=1500):
                btn.click(timeout=5000)
                _safe_wait(page, 1200)
                return True
        except Exception:
            pass
        try:
            link = page.get_by_text(re.compile(pat, re.I)).first
            if link.is_visible(timeout=1200):
                link.click(timeout=5000)
                _safe_wait(page, 1200)
                return True
        except Exception:
            pass
    return False


def _action_name_re(name: str):
    """Continue/Next/Sign in, plus optional 'with email' — never a bare substring of Google."""
    return re.compile(rf"^{re.escape(name)}(\s+with\s+email)?$", re.I)


def _click_login_action(page, names: list[str], *, allow_sso: bool = False) -> bool:
    """Click Continue / Sign in / email-entry. Never Google/Apple/Facebook unless allow_sso."""
    for name in names:
        pat = _action_name_re(name)
        locators = []
        for role in ("button", "link"):
            try:
                locators.append(page.get_by_role(role, name=pat).first)
            except Exception:
                pass
        try:
            locators.append(page.get_by_text(pat).first)
        except Exception:
            pass
        for loc in locators:
            try:
                if not loc.is_visible(timeout=800):
                    continue
                label = name
                try:
                    label = (loc.inner_text(timeout=400) or name).strip()
                except Exception:
                    pass
                if not allow_sso and _SSO_LABEL.search(label):
                    continue
                loc.click(timeout=5000)
                _safe_wait(page, 800)
                _hunt_log(f"Clicked login action {name!r} ({label!r})")
                return True
            except Exception:
                continue
    return False


def _click_google_sso_button(page) -> bool:
    """Find Continue/Sign in with Google — never random 'Google Cloud' marketing links."""
    if _click_login_action(
        page,
        ["Continue with Google", "Sign in with Google", "Log in with Google", "Sign up with Google"],
        allow_sso=True,
    ):
        return True

    sso_ok = re.compile(
        r"^(continue|sign\s*in|log\s*in|sign\s*up).{0,24}google$"
        r"|^google$"
        r"|^sign\s*in$"  # icon-only sometimes
        ,
        re.I,
    )
    sso_bad = re.compile(
        r"vertex|cloud\s*console|workspace|docs|privacy|terms|cloud.?s\b|marketing",
        re.I,
    )

    for role in ("button", "link"):
        try:
            locs = page.get_by_role(role, name=re.compile(r"google", re.I))
            n = min(locs.count(), 8)
        except Exception:
            n = 0
        for i in range(n):
            try:
                loc = locs.nth(i)
                if not loc.is_visible(timeout=800):
                    continue
                label = ""
                try:
                    label = (loc.inner_text(timeout=400) or "").strip()
                except Exception:
                    pass
                try:
                    aria = (loc.get_attribute("aria-label") or "").strip()
                    if aria:
                        label = label or aria
                except Exception:
                    pass
                check = (label or "google").strip()
                if sso_bad.search(check):
                    continue
                # Accept exact SSO phrases, bare "Google" button, or aria Google
                if not (
                    sso_ok.search(check)
                    or re.fullmatch(r"google", check, re.I)
                    or re.search(r"(continue|sign\s*in|log\s*in).{0,16}google", check, re.I)
                ):
                    continue
                loc.click(timeout=5000)
                _safe_wait(page, 800)
                _hunt_log(f"Clicked Google SSO via role={role} ({check})")
                return True
            except Exception:
                continue

    for sel in (
        '[data-provider="google"]',
        'button[aria-label*="Google" i]',
        'button[data-testid*="google" i]',
    ):
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=1000):
                loc.click(timeout=5000)
                _safe_wait(page, 800)
                _hunt_log(f"Clicked Google SSO via {sel}")
                return True
        except Exception:
            continue
    return False


def _open_email_signin(page) -> bool:
    """Reveal the email field (Clerk / ElevenLabs landing)."""
    if _email_visible(page) or _password_visible(page):
        return _email_visible(page)
    _progress("looking for email field")
    clicked = _click_login_action(page, [
        "Sign in with email",
        "Continue with email",
        "Log in with email",
        "Use email",
        "Sign in with Email",
    ])
    _safe_wait(page, 1500)
    return clicked or _email_visible(page)


def _dismiss_popups(page) -> None:
    _click_any(page, ["Accept", "Accept all", "Got it", "I agree", "OK", "Allow"])

# ── Google SSO ───────────────────────────────────────────

def _google_challenge_visible(page) -> bool:
    """2FA / Verify it's you / phone challenge."""
    try:
        if page.get_by_text(
            re.compile(
                r"verify it.?s you|2-?step|two.?step|enter (the )?code|"
                r"check your phone|authenticator|recovery|confirm it.?s you",
                re.I,
            )
        ).first.is_visible(timeout=600):
            return True
    except Exception:
        pass
    return False


def _google_url(page) -> str:
    try:
        return (page.url or "").lower()
    except Exception:
        return ""


def _google_on_password_step(page) -> bool:
    """True when Google is asking for the password (not identifier / chooser)."""
    url = _google_url(page)
    if any(
        x in url
        for x in (
            "/challenge/pwd",
            "/challenge/password",
            "challenge/pwd",
            "pwd?",
            "/signin/pwd",
        )
    ):
        return True
    # Password field up and identifier step not active
    if _password_visible(page) and not _google_on_identifier_step(page):
        return True
    return False


def _google_on_identifier_step(page) -> bool:
    url = _google_url(page)
    if "accountchooser" in url:
        return False
    if any(x in url for x in ("/identifier", "signin/identifier", "servicelogin")):
        return True
    # Email box visible + no password = identifier
    return _email_visible(page) and not _password_visible(page)


def _google_on_account_chooser(page) -> bool:
    url = _google_url(page)
    if "accountchooser" in url:
        return True
    try:
        if page.get_by_text(
            re.compile(r"choose an account|select an account|choose your account", re.I)
        ).first.is_visible(timeout=500):
            return True
    except Exception:
        pass
    return False


def _pick_google_account(page, email: str) -> bool:
    """Click the correct account tile on Google account chooser only.

    Never click the email label on the password page — that bounces back to
    identifier and creates the email→Next→back loop.
    """
    email_l = (email or "").strip().lower()
    if not email_l:
        return False

    # Hard stop: password / challenge pages show the email as text — do NOT click it
    if _google_on_password_step(page) or _password_visible(page):
        _hunt_log("Skip account pick — already on password/challenge step")
        return False
    # Identifier step uses fill, not tile click
    if _google_on_identifier_step(page):
        return False

    # Prefer data-identifier / data-email attributes (real chooser tiles)
    for sel in (
        f'div[data-identifier="{email_l}"]',
        f'div[data-email="{email_l}"]',
        f'[data-identifier="{email_l}"]',
        f'li[data-identifier="{email_l}"]',
        f'div[data-identifier*="{email_l}"]',
    ):
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=1500):
                loc.click(timeout=5000)
                _progress(f"Selected Google account {email}")
                _safe_wait(page, 3000)
                return True
        except Exception:
            continue

    # Fallback text match ONLY on account chooser
    if _google_on_account_chooser(page):
        try:
            acct = page.get_by_text(re.compile(rf"^{re.escape(email)}$", re.I)).first
            if acct.is_visible(timeout=2000):
                acct.click(timeout=5000)
                _progress(f"Selected Google account {email}")
                _safe_wait(page, 3000)
                return True
        except Exception:
            pass

    # "Use another account" — only on chooser
    if _google_on_account_chooser(page):
        try:
            other = page.get_by_text(re.compile(r"use another account|add another account", re.I)).first
            if other.is_visible(timeout=1500):
                other.click(timeout=5000)
                _safe_wait(page, 2000)
                _progress("Chose Use another account")
                return False  # caller will fill email
        except Exception:
            pass
    return False


def _google_auth_done(page) -> bool:
    """True when SSO finished — any tab left accounts.google for the app."""
    try:
        pages = list(page.context.pages)
    except Exception:
        pages = [page]
    for p in pages:
        try:
            u = (p.url or "").lower()
        except Exception:
            continue
        if not u or u.startswith("about:"):
            continue
        if "accounts.google" in u:
            continue
        if "myaccount.google.com" in u and "signin" not in u and "servicelogin" not in u:
            return True
        # Provider console / app (not a login screen)
        if any(x in u for x in ("/login", "sign-in", "signin", "/auth/")):
            continue
        return True
    return False


def _click_google_consent(page) -> bool:
    """OAuth consent after account pick — Prefer Allow."""
    return _click_login_action(
        page,
        ["Allow", "Continue", "Confirm", "Accept", "Yes"],
    )


def _on_google_accounts(page) -> bool:
    try:
        return "accounts.google" in (page.url or "").lower()
    except Exception:
        return False


def _google_already_signed_in(page, email: str = "") -> bool:
    """True if Chrome profile already has an active Google session."""
    try:
        url = (page.url or "").lower()
    except Exception:
        url = ""
    if "myaccount.google.com" in url and "servicelogin" not in url and "signin" not in url:
        return True
    try:
        # Logged-in Google often shows no identifier/password form
        if _on_google_accounts(page) and not _email_visible(page) and not _password_visible(page):
            if not _google_challenge_visible(page) and not _captcha_visible(page):
                # Account chooser lists accounts — not fully "in" yet
                try:
                    if page.get_by_text(re.compile(r"choose an account|select an account", re.I)).first.is_visible(timeout=400):
                        return False
                except Exception:
                    pass
                return True
    except Exception:
        pass
    return False


def _ensure_google_session(page, email: str, password: str) -> str:
    """Warm Jarvis Google login in the persistent Chrome profile before SSO sites.

    Once this succeeds, ElevenLabs/OpenRouter/etc. can click 'Continue with Google'
    without asking the human to sign in again.
    """
    if not email or not password:
        return "password_failed"
    _progress(f"Warming Google session as {email}")
    try:
        page.goto(
            "https://accounts.google.com/ServiceLogin?hl=en&continue=https%3A%2F%2Fmyaccount.google.com%2F",
            wait_until="domcontentloaded",
            timeout=60000,
        )
    except Exception as exc:
        _hunt_log(f"Google warm load error: {exc}")
    _safe_wait(page, 2500)
    try:
        cur = (page.url or "").lower()
        if "myaccount.google.com" in cur and "signin" not in cur and "servicelogin" not in cur:
            _progress("Google session already active")
            return "ok"
    except Exception:
        pass
    if _google_already_signed_in(page, email):
        _progress("Google session already active")
        return "ok"
    outcome = _complete_google_auth(page, email, password, timeout_sec=90)
    if outcome == "ok":
        _progress("Google session ready for SSO")
        # Confirm by hitting My Account once
        try:
            page.goto(
                "https://myaccount.google.com/",
                wait_until="domcontentloaded",
                timeout=45000,
            )
            _safe_wait(page, 1500)
        except Exception:
            pass
    return outcome


def _complete_google_auth(page, email: str, password: str, *, timeout_sec: int = 45) -> str:
    """Finish Google login after SSO click: chooser → email → password → done.

    Returns: ok | challenge | sso_blocked | password_failed | pending
    """
    deadline = time.time() + max(timeout_sec, 5)
    idle = 0
    pwd_attempts = 0
    email_next_clicks = 0
    account_picks = 0
    while time.time() < deadline:
        try:
            if _google_auth_done(page):
                _progress("Google sign-in succeeded")
                return "ok"
            url = (page.url or "").lower()
            if "myaccount.google.com" in url and "signin" not in url and "servicelogin" not in url:
                _progress("Google sign-in succeeded")
                return "ok"
            if not _is_login_url(page.url) and not _on_google_accounts(page):
                _progress("Google sign-in succeeded")
                return "ok"
        except Exception:
            pass

        if _google_challenge_visible(page):
            # Password challenge is OK — 2FA / phone is not
            if not _google_on_password_step(page) and not _password_visible(page):
                _progress(
                    "Google asks to verify — complete it in Chrome once; later hunts reuse this profile"
                )
                return "challenge"

        if _captcha_visible(page):
            _progress("Google CAPTCHA — complete it in Chrome once; later hunts reuse this profile")
            return "challenge"

        # PASSWORD FIRST when visible — never bounce to email/chooser
        if _password_visible(page) or _google_on_password_step(page):
            if pwd_attempts >= 2:
                # Often bot-check / wrong pwd / slow UI — leave Chrome open for one human finish
                _hunt_log("Google password still stuck after 2 attempts — leaving for human verify")
                _progress(
                    "Password filled but Google did not advance — complete Next/Verify in Chrome once; "
                    "later hunts reuse this session"
                )
                return "challenge"
            if not _password_visible(page):
                _safe_wait(page, 1200)
            if _password_visible(page):
                _progress("Google password step")
                pwd_attempts += 1
                outcome = _finish_password(page, password)
                if outcome == "challenge":
                    return "challenge"
                if outcome in ("password_failed", "no_password"):
                    return "password_failed"
                if outcome == "password_stuck":
                    idle += 1
                    _safe_wait(page, 1500)
                    continue
                if outcome == "ok":
                    _safe_wait(page, 2000)
                    try:
                        url = (page.url or "").lower()
                        if "myaccount.google.com" in url or (
                            not _is_login_url(page.url) and not _on_google_accounts(page)
                        ):
                            _progress("Google sign-in succeeded")
                            return "ok"
                    except Exception:
                        pass
                _safe_wait(page, 3500)
                idle = 0
                continue
            idle += 1
            _safe_wait(page, 800)
            continue

        # Account chooser (only when NOT on password)
        if _google_on_account_chooser(page):
            if account_picks >= 3:
                _hunt_log("Account chooser loop — aborting pick")
                return "sso_blocked"
            if _pick_google_account(page, email):
                account_picks += 1
                _safe_wait(page, 2000)
                # Warm session: OAuth consent / Allow / redirect to provider
                for _ in range(6):
                    if _click_google_consent(page):
                        _safe_wait(page, 2800)
                    if _google_auth_done(page):
                        _progress("Google sign-in succeeded")
                        return "ok"
                    if _password_visible(page) or _google_on_password_step(page):
                        break
                    if _google_challenge_visible(page) and not _password_visible(page):
                        return "challenge"
                    _safe_wait(page, 1200)
                idle = 0
                continue
            # No tile — wait briefly for password / identifier
            idle += 1
            _safe_wait(page, 1000)
            continue

        # EMAIL / identifier — max 2 Next clicks (no forever loop)
        need_email = _needs_email_before_password(page, email) or (
            _google_on_identifier_step(page)
            and _email_visible(page)
            and not _email_already_filled(page, email)
        )
        if need_email:
            if email_next_clicks >= 2 and _email_already_filled(page, email):
                # Already submitted — wait for password instead of clicking Next again
                _hunt_log("Email already submitted — waiting for password field")
                idle += 1
                _safe_wait(page, 1500)
                continue
            _progress(f"Google email step — entering {email}")
            filled = _fill_email(page, email)
            if not filled:
                for sel in ("#identifierId", 'input[name="identifier"]', 'input[type="email"]'):
                    try:
                        loc = page.locator(sel).first
                        if loc.is_visible(timeout=1000):
                            loc.click(timeout=2000)
                            loc.fill("", timeout=1500)
                            loc.press_sequentially(email, delay=20)
                            _hunt_log(f"OK forced Google email via {sel}")
                            filled = True
                            break
                    except Exception:
                        continue
            if filled:
                _safe_wait(page, 500)
                if email_next_clicks < 2:
                    if not _click_login_action(page, ["Next", "Continue"]):
                        try:
                            page.keyboard.press("Enter")
                        except Exception:
                            pass
                    email_next_clicks += 1
                _safe_wait(page, 2800)
                idle = 0
                continue
            idle += 1
            continue

        # Email filled on identifier — one Next if not yet clicked enough
        if (
            _google_on_identifier_step(page)
            and _email_already_filled(page, email)
            and email_next_clicks < 2
            and not _password_visible(page)
        ):
            _progress("Google email filled — clicking Next")
            if not _click_login_action(page, ["Next", "Continue"]):
                try:
                    page.keyboard.press("Enter")
                except Exception:
                    pass
            email_next_clicks += 1
            _safe_wait(page, 2800)
            idle = 0
            continue

        # Consent only — NEVER click bare Next while forms are active
        if _on_google_accounts(page) and not _email_visible(page) and not _password_visible(page):
            if _click_google_consent(page):
                _safe_wait(page, 3000)
                if _google_auth_done(page):
                    _progress("Google sign-in succeeded")
                    return "ok"
                idle = 0
                continue

        idle += 1
        if idle >= 14:
            break
        _safe_wait(page, 700)

    if _on_google_accounts(page) or _is_login_url(page.url):
        return "sso_blocked"
    return "ok"


def _google_auth_page(page):
    """Prefer a popup/tab that landed on accounts.google.com after SSO click."""
    try:
        ctx = page.context
        for p in list(ctx.pages):
            try:
                if "accounts.google" in (p.url or "").lower():
                    try:
                        p.bring_to_front()
                    except Exception:
                        pass
                    return p
            except Exception:
                continue
    except Exception:
        pass
    return page


def _try_google_sso(page, email: str, password: str = "") -> str:
    """Click Google once and complete auth with JARVIS credentials.

    Returns outcome string (ok / challenge / sso_blocked / password_failed / skipped).
    """
    # SPAs (Anthropic etc.) need a moment before the Google button mounts
    deadline = time.time() + 25
    clicked = False
    popup = None
    while time.time() < deadline and not clicked:
        try:
            with page.expect_popup(timeout=2500) as pop_info:
                clicked = _click_google_sso_button(page)
                if not clicked:
                    raise RuntimeError("no_google_button")
            popup = pop_info.value
            break
        except Exception:
            if not clicked:
                clicked = _click_google_sso_button(page)
                if clicked:
                    break
            _safe_wait(page, 700)
    if not clicked:
        return "skipped"
    _progress("Clicked Google sign-in")
    _safe_wait(page, 2500)

    # Wait briefly for popup / redirect / account chooser (warm session often auto-finishes)
    auth_page = popup or page
    start_url = ""
    try:
        start_url = (page.url or "").lower()
    except Exception:
        pass
    for _ in range(16):
        auth_page = popup or _google_auth_page(page)
        try:
            cur = (page.url or "").lower()
            # Provider accepted Google — left login (must actually change off login)
            if (
                cur
                and cur != start_url
                and not _is_login_url(page.url)
                and not _on_google_accounts(page)
                and "google.com" not in cur
            ):
                _progress("Google sign-in succeeded")
                return "ok"
        except Exception:
            pass
        if (
            _on_google_accounts(auth_page)
            or _password_visible(auth_page)
            or _email_visible(auth_page)
            or _google_on_account_chooser(auth_page)
        ):
            break
        # Consent on main page
        if _click_login_action(auth_page, ["Continue", "Allow", "Accept", "Confirm"]):
            _safe_wait(page, 1500)
            continue
        _safe_wait(page, 500)
    else:
        try:
            cur = (page.url or "").lower()
            if (
                cur
                and cur != start_url
                and not _is_login_url(page.url)
                and "google.com" not in cur
            ):
                return "ok"
        except Exception:
            pass

    auth_page = popup or _google_auth_page(page)
    try:
        auth_page.bring_to_front()
    except Exception:
        pass

    if not password:
        if _pick_google_account(auth_page, email):
            return "pending"
        if _on_google_accounts(auth_page) and _fill_email(auth_page, email):
            _click_login_action(auth_page, ["Next", "Continue"])
            return "pending"
        return "skipped"

    return _complete_google_auth(auth_page, email, password, timeout_sec=90)


# ── Login flows ──────────────────────────────────────────

def _wait_for_password(page, timeout_sec: int = 30) -> bool:
    return _wait_login_advance(page, timeout_sec=timeout_sec) == "password"


def _wait_login_advance(page, timeout_sec: int = 15) -> str:
    """After Continue: password step, logged in, captcha, or still email."""
    deadline = time.time() + max(timeout_sec, 0)
    while True:
        try:
            if not _is_login_url(page.url):
                return "logged_in"
        except Exception:
            pass
        if _password_visible(page):
            return "password"
        if _captcha_visible(page):
            return "captcha"
        if time.time() >= deadline:
            break
        _safe_wait(page, 500)
    try:
        if not _is_login_url(page.url):
            return "logged_in"
    except Exception:
        pass
    if _password_visible(page):
        return "password"
    if _captcha_visible(page):
        return "captcha"
    return "email"


def _submit_email_step(page) -> None:
    if _click_login_action(page, ["Continue", "Next", "Continue with email"]):
        return
    try:
        page.keyboard.press("Enter")
    except Exception:
        pass


def _click_google_password_next(page) -> bool:
    """Click Google's real password Next (#passwordNext), not a stale identifier button."""
    for sel in (
        "#passwordNext",
        "button#passwordNext",
        'div#passwordNext button',
        'button[jsname="LgbsSe"]',
    ):
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=1200):
                loc.click(timeout=5000)
                _hunt_log(f"Clicked Google password Next via {sel}")
                return True
        except Exception:
            continue
    # Fallback: role button named Next, but only if password field is still focused/visible
    if _password_visible(page):
        return _click_login_action(page, ["Next", "Continue", "Sign in"])
    return False


def _submit_password_step(page) -> None:
    # Google password challenge almost always uses #passwordNext
    if _on_google_accounts(page):
        if _click_google_password_next(page):
            return
        if _click_login_action(page, ["Next", "Continue", "Sign in", "Log in", "Submit"]):
            return
    elif _click_login_action(page, ["Sign in", "Log in", "Continue", "Next", "Submit"]):
        return
    try:
        page.keyboard.press("Enter")
    except Exception:
        pass


def _goto_login(page, login_url: str) -> None:
    try:
        page.goto(login_url, wait_until="domcontentloaded", timeout=60000)
    except Exception as exc:
        _hunt_log(f"Login page load error: {exc}")
    _safe_wait(page, 2000)


def _password_field_has_value(page) -> bool:
    for sel in PASSWORD_SELECTORS:
        try:
            loc = page.locator(sel).first
            if not loc.is_visible(timeout=400):
                continue
            val = loc.input_value(timeout=800) or ""
            if len(val) >= 4:
                return True
        except Exception:
            continue
    return False


def _finish_password(page, password: str) -> str:
    _progress("Password step — filling the password field only")
    if not _fill_password(page, password):
        return "no_password"
    _safe_wait(page, 600)
    if not _password_field_has_value(page):
        # Retype once — React/Google sometimes drops the first fill
        _hunt_log("Password field empty after fill — retyping")
        if not _fill_password(page, password):
            return "no_password"
        _safe_wait(page, 500)
    # Blur then submit (Google validates on blur sometimes)
    try:
        page.keyboard.press("Tab")
    except Exception:
        pass
    _safe_wait(page, 300)
    _submit_password_step(page)
    _safe_wait(page, 4000)
    if _invalid_credentials_visible(page):
        _hunt_log("Invalid Google/site password visible after submit")
        return "password_failed"
    if _google_challenge_visible(page) and not _password_visible(page):
        return "challenge"
    if _captcha_visible(page):
        return "challenge"
    # Success paths
    try:
        url = (page.url or "").lower()
        if "myaccount.google.com" in url and "signin" not in url:
            return "ok"
        if not _is_login_url(page.url) and not _on_google_accounts(page):
            return "ok"
        if _on_google_accounts(page) and not _password_visible(page) and not _email_visible(page):
            return "ok"
    except Exception:
        pass
    # Google: if password field still up after Next, try #passwordNext + Enter once more
    if _on_google_accounts(page) and _password_visible(page):
        _click_google_password_next(page)
        try:
            page.keyboard.press("Enter")
        except Exception:
            pass
        _safe_wait(page, 3500)
        if _invalid_credentials_visible(page):
            return "password_failed"
        if _google_challenge_visible(page) and not _password_visible(page):
            return "challenge"
        if _password_visible(page):
            # Likely wrong password OR Google blocking automation — leave for human
            _hunt_log("Google password field still visible after Next/Enter")
            return "password_stuck"
    return "ok"


def _email_password_rounds(
    page,
    email: str,
    password: str,
    provider_id: str,
    *,
    wait_sec: int = 20,
    open_email_form: bool = False,
) -> str:
    email_fills = 0
    max_email_fills = 2
    pwd_wait = wait_sec

    for _round in range(2):
        try:
            if not _is_login_url(page.url):
                return "ok"
        except Exception:
            pass
        # Password only if email already correct (or no email field left)
        if _password_visible(page) and not _needs_email_before_password(page, email):
            return _finish_password(page, password)
        if _captcha_visible(page):
            _progress("stuck — complete CAPTCHA in Chrome, then say get api key again")
            return "captcha"

        if open_email_form and not _email_visible(page) and not _password_visible(page):
            _open_email_signin(page)

        if _password_visible(page) and not _needs_email_before_password(page, email):
            return _finish_password(page, password)

        if _email_already_filled(page, email):
            _progress("Email already filled — clicking Continue (not filling again)")
        elif email_fills >= max_email_fills:
            _progress(
                "stuck — complete CAPTCHA or sign-in in Chrome, then say "
                f"get {provider_id.replace('_', ' ')} api key again"
            )
            return "stuck_email"
        else:
            if not _email_visible(page):
                _progress("looking for email field")
                if open_email_form:
                    _open_email_signin(page)
            if not _email_visible(page):
                if _password_visible(page) and not _needs_email_before_password(page, email):
                    return _finish_password(page, password)
                _progress(f"Could not find the email field for {provider_id}")
                return "wrong_field"
            _progress(f"Entering email {email}")
            if not _fill_email(page, email):
                if _password_visible(page) and not _needs_email_before_password(page, email):
                    return _finish_password(page, password)
                _progress(f"Could not find the email field for {provider_id}")
                return "wrong_field"
            email_fills += 1
            _progress("filled email")

        _progress("waiting for password")
        _submit_email_step(page)
        step = _wait_login_advance(page, timeout_sec=pwd_wait)
        if step == "password":
            if _needs_email_before_password(page, email):
                _progress(f"Password visible but email still needed — entering {email}")
                if _fill_email(page, email):
                    email_fills += 1
                    _submit_email_step(page)
                    step = _wait_login_advance(page, timeout_sec=pwd_wait)
            if step == "password" and not _needs_email_before_password(page, email):
                return _finish_password(page, password)
        if step == "logged_in":
            return "ok"
        if step == "captcha":
            _progress("stuck — complete CAPTCHA in Chrome, then say get api key again")
            return "captcha"
        _hunt_log("Still on email step after Continue")

    if _password_visible(page) and not _needs_email_before_password(page, email):
        return _finish_password(page, password)
    _progress(
        "stuck — complete CAPTCHA or sign-in in Chrome, then say "
        f"get {provider_id.replace('_', ' ')} api key again"
    )
    return "stuck_email"


def _invalid_credentials_visible(page) -> bool:
    try:
        if page.get_by_text(
            re.compile(
                r"invalid (email|password|credentials)|wrong password|"
                r"couldn.?t (find|sign)|incorrect (email|password)|"
                r"authentication failed|login failed|doesn.?t (match|exist)",
                re.I,
            )
        ).first.is_visible(timeout=800):
            return True
    except Exception:
        pass
    return False


def _google_then_email_fallback(page, email: str, password: str, login_url: str) -> str | None:
    """Try Google once (full auth). Only used when email field is missing."""
    _progress("Trying Google sign-in")
    outcome = _try_google_sso(page, email, password)
    if outcome == "ok":
        _progress("Google sign-in succeeded")
        return "ok"
    if outcome in ("challenge", "password_failed", "sso_blocked"):
        return outcome
    try:
        if "accounts.google" in (page.url or "").lower() and login_url:
            _progress("Google sign-in did not finish — returning to login page")
            _goto_login(page, login_url)
    except Exception:
        pass
    return None


def _login_elevenlabs(page, email: str, password: str, *, wait_sec: int = 20) -> str:
    """ElevenLabs: warm Google session, then SSO — Gmail accounts have no EL password."""
    _progress(f"ElevenLabs — ensuring Google session as {email}")
    warm = _ensure_google_session(page, email, password)
    if warm in ("challenge", "password_failed"):
        return warm
    # Back to ElevenLabs login after warming Google
    _goto_login(page, PROVIDERS["elevenlabs"]["login"])
    _dismiss_popups(page)
    _progress(f"ElevenLabs — Google SSO as {email}")
    outcome = _try_google_sso(page, email, password)
    if outcome == "ok":
        return "ok"
    if outcome in ("challenge", "password_failed"):
        return outcome
    if outcome == "sso_blocked":
        more = _complete_google_auth(page, email, password, timeout_sec=75)
        if more == "ok":
            return "ok"
        if more in ("challenge", "password_failed", "sso_blocked"):
            # One more warm+retry cycle before giving up
            warm2 = _ensure_google_session(page, email, password)
            if warm2 == "ok":
                _goto_login(page, PROVIDERS["elevenlabs"]["login"])
                g3 = _try_google_sso(page, email, password)
                if g3 == "ok":
                    return "ok"
                if g3 != "skipped":
                    return g3
            return more

    # Google button missing — email form (non-Google accounts only)
    if outcome == "skipped":
        _progress("No Google button — trying email sign-in")
        _open_email_signin(page)
        result = _email_password_rounds(
            page, email, password, "elevenlabs",
            wait_sec=wait_sec, open_email_form=True,
        )
        if result == "ok":
            return "ok"
        if _invalid_credentials_visible(page):
            _progress("Email/password rejected — retrying Google sign-in")
            g2 = _try_google_sso(page, email, password)
            return g2 if g2 != "skipped" else "sso_blocked"
        return result

    # Incomplete SSO — keep Chrome open; profile may finish on next hunt
    _progress(
        "Google SSO incomplete for ElevenLabs — Chrome left open. "
        "If a Verify prompt appears, finish it once; later hunts reuse the session."
    )
    return "sso_blocked"


def _login_fail_message(provider_id: str, outcome: str) -> str:
    label = provider_id.replace("_", " ")
    if outcome == "stuck_email":
        return (
            f"Stuck on the email screen for {label} (or CAPTCHA / Clerk asked for email again). "
            f"Complete sign-in in Chrome, then say get {label} api key again."
        )
    if outcome == "captcha" or outcome == "challenge":
        return (
            f"Google/site verification on {label} (CAPTCHA or Verify it's you). "
            f"Complete it in Chrome as {get_user_email() or 'Jarvis'}, "
            f"then say get {label} api key again."
        )
    if outcome == "wrong_field":
        return (
            f"Could not find the email field for {label}. Finish sign-in in Chrome, "
            f"then say get {label} api key again."
        )
    if outcome == "no_password" or outcome == "password_failed":
        return (
            f"Could not enter the password for {label}. "
            f"Check JARVIS_PASSWORD in .env, complete sign-in in Chrome, "
            f"then say get {label} api key again."
        )
    if outcome == "sso_blocked":
        return (
            f"Google sign-in did not finish for {label} (Jarvis Chrome profile). "
            f"If Chrome shows Verify/CAPTCHA, complete it once — Jarvis will reuse that session. "
            f"Confirm JARVIS_PASSWORD in .env, then say get {label} api key again."
        )
    return (
        f"Chrome is still open on {label}. Finish sign-in if needed, "
        f"then say get {label} api key again."
    )


def _do_login(page, email: str, password: str, provider_id: str, *, wait_sec: int = 20) -> str:
    try:
        page.wait_for_load_state("domcontentloaded", timeout=30000)
    except Exception:
        pass
    _safe_wait(page, 2000)
    _dismiss_popups(page)

    cfg = PROVIDERS.get(provider_id, {})

    if provider_id == "elevenlabs":
        return _login_elevenlabs(page, email, password, wait_sec=wait_sec)

    if cfg.get("google_sso"):
        _progress(f"Trying Google sign-in for {provider_id} as {email}")
        outcome = _try_google_sso(page, email, password)
        if outcome == "ok":
            return "ok"
        if outcome in ("challenge", "password_failed", "sso_blocked"):
            # Stay on Google page so user can finish — do not abandon mid-flow
            if _on_google_accounts(page) or _password_visible(page) or _google_challenge_visible(page):
                return outcome
        # If still on Google with password field, finish password
        if _on_google_accounts(page) and _password_visible(page):
            fin = _finish_password(page, password)
            if fin == "ok":
                _safe_wait(page, 3000)
                try:
                    if not _is_login_url(page.url) and not _on_google_accounts(page):
                        return "ok"
                except Exception:
                    pass
            else:
                return "password_failed"
        try:
            if "accounts.google" in (page.url or "").lower():
                more = _complete_google_auth(page, email, password)
                if more == "ok":
                    return "ok"
                if more in ("challenge", "password_failed", "sso_blocked"):
                    return more
                # Gmail accounts must finish Google SSO — site email/password = invalid credentials
                if (email or "").lower().endswith("@gmail.com"):
                    _progress(
                        "Google sign-in incomplete — finish in Chrome as Jarvis "
                        "(site email/password will fail for Gmail)"
                    )
                    return "sso_blocked"
                _progress("Google incomplete — trying provider email login")
                login_url = cfg.get("login")
                if login_url:
                    _goto_login(page, login_url)
        except Exception:
            pass
        # Jarvis Gmail must finish Google SSO — never site email/password (invalid for Google accounts)
        if (email or "").lower().endswith("@gmail.com"):
            if outcome == "ok":
                return "ok"
            if outcome == "skipped":
                _progress("Google button not found — retrying once")
                _safe_wait(page, 1500)
                try:
                    page.mouse.wheel(0, 500)
                except Exception:
                    pass
                outcome = _try_google_sso(page, email, password)
                if outcome == "ok":
                    return "ok"
            if outcome in ("challenge", "password_failed", "sso_blocked", "pending", "skipped"):
                return "sso_blocked" if outcome in ("skipped", "pending") else outcome
            return "sso_blocked"

    return _email_password_rounds(
        page, email, password, provider_id, wait_sec=wait_sec, open_email_form=False,
    )


def _is_login_url(url: str) -> bool:
    u = url.lower()
    return any(x in u for x in ("sign-in", "signin", "/login", "/auth", "sign_up", "accounts.google"))


def _wait_logged_in(page, timeout_sec: int = 90) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            if not _is_login_url(page.url):
                return True
        except Exception:
            pass
        _safe_wait(page, 2000)
    return False


def _goto_keys_page(page, keys_url: str) -> bool:
    """Navigate to keys URL without hanging forever on slow consoles."""
    try:
        page.goto(keys_url, wait_until="commit", timeout=25000)
    except Exception as exc:
        _hunt_log(f"Keys page load: {exc}")
        try:
            page.goto(keys_url, wait_until="domcontentloaded", timeout=20000)
        except Exception as exc2:
            _hunt_log(f"Keys page retry: {exc2}")
    _safe_wait(page, 2000)
    try:
        return not _is_login_url(page.url)
    except Exception:
        return False

# ── Key extraction ───────────────────────────────────────

_GENERIC_KEY_PATTERN = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{20,}|gsk_[A-Za-z0-9]{20,}|sk_[a-f0-9]{20,}"
    r"|hf_[A-Za-z0-9]{20,}|AIza[A-Za-z0-9_-]{30,}|nvapi-[A-Za-z0-9_-]{20,}"
    r"|sk-ant-[A-Za-z0-9_-]{20,}|sk-or-[A-Za-z0-9_-]{20,})"
)


def _extract_key_from_page(page, pattern: re.Pattern[str]) -> str | None:
    # 1. HTML body scan
    try:
        body = page.content()
        matches = pattern.findall(body)
        if matches:
            _hunt_log(f"Found key in page body: {mask_secret(matches[0])}")
            return matches[0]
    except Exception:
        pass

    # 2. Input fields
    try:
        for inp in page.locator("input").all()[:40]:
            try:
                val = inp.input_value(timeout=600)
                if val and pattern.search(val):
                    key = pattern.search(val).group(0)
                    _hunt_log(f"Found key in input: {mask_secret(key)}")
                    return key
            except Exception:
                continue
    except Exception:
        pass

    # 3. Copy buttons
    try:
        import pyperclip
        for label in ("Copy", "Copy key", "Copy API", "Copy to clipboard"):
            try:
                btn = page.get_by_role("button", name=re.compile(label, re.I)).first
                if btn.is_visible(timeout=1500):
                    btn.click()
                    _safe_wait(page, 800)
                    clip = pyperclip.paste()
                    if clip and pattern.search(clip):
                        key = pattern.search(clip).group(0)
                        _hunt_log(f"Found key via clipboard: {mask_secret(key)}")
                        return key
            except Exception:
                continue
    except ImportError:
        pass

    return None

# ── Main Playwright fetch ────────────────────────────────

def _playwright_fetch(provider_id: str, email: str, password: str) -> str | None:
    from playwright.sync_api import sync_playwright

    global _LAST_HUNT_NOTE
    _LAST_HUNT_NOTE = ""

    cfg = PROVIDERS[provider_id]
    pattern = re.compile(cfg["pattern"])
    CHROME_PROFILE.mkdir(parents=True, exist_ok=True)
    _release_browser()
    _unlock_chrome_profile()

    _hunt_log(f"Starting hunt for {provider_id}")

    manager = sync_playwright()
    pw = manager.__enter__()
    context = None
    keep_open = False

    try:
        context = _launch_persistent(pw, channel="chrome")

        def _page():
            nonlocal page
            try:
                _ = page.url
                return page
            except Exception:
                page = context.pages[0] if context.pages else context.new_page()
                return page

        page = context.pages[0] if context.pages else context.new_page()

        # Warm Google once for SSO providers so human sign-in is not required every hunt
        if cfg.get("google_sso") and email and password:
            try:
                warm = _ensure_google_session(page, email, password)
                _hunt_log(f"Google warm: {warm}")
                page = _page()
            except Exception as exc:
                _hunt_log(f"Google warm skipped: {exc}")
                page = _page()

        # ── Phase 1: Try keys page directly (may already be signed in) ──
        # Skip for flaky SSO consoles after warm — keys URL often aborts mid-redirect
        _progress(f"Opening {provider_id} keys page")
        key = None
        page = _page()
        skip_keys_first = bool(cfg.get("google_sso")) and provider_id in (
            "anthropic", "openai", "mistral", "cohere", "fireworks", "cerebras",
        )
        if not skip_keys_first and _goto_keys_page(page, cfg["keys"]):
            _click_any(page, [
                "Create", "Create API key", "Create Key", "Generate",
                "New", "Add", "+ Create", "Create an API key", "Reveal", "Show",
            ])
            _safe_wait(page, 2500)
            key = _extract_key_from_page(page, pattern)

        # ── Phase 2: Login ──
        if not key:
            _progress(f"Signing in to {provider_id}")
            page = _page()
            try:
                page.goto(cfg["login"], wait_until="domcontentloaded", timeout=60000)
            except Exception as exc:
                _hunt_log(f"Login page load error: {exc}")
                page = _page()
            _safe_wait(page, 2500)
            outcome = _do_login(page, email, password, provider_id)
            page = _page()
            if outcome != "ok":
                _LAST_HUNT_NOTE = _login_fail_message(provider_id, outcome)
                _progress(_LAST_HUNT_NOTE)

            _progress("Waiting for login to complete...")
            _wait_logged_in(page, timeout_sec=45 if outcome == "ok" else 25)
            page = _page()

            # ── Phase 3: Navigate to keys page ──
            _progress(f"Opening {provider_id} API keys page")
            if _goto_keys_page(page, cfg["keys"]):
                _click_any(page, [
                    "Create", "Create API key", "Create Key", "Generate",
                    "New", "Add", "+ Create", "Create an API key", "Reveal", "Show",
                ])
                _safe_wait(page, 3000)
                key = _extract_key_from_page(page, pattern)

        # ── Phase 4: Retry with reload ──
        if not key:
            _hunt_log("Phase 4: reload + retry")
            try:
                page.reload(wait_until="domcontentloaded")
            except Exception:
                pass
            _safe_wait(page, 3000)
            key = _extract_key_from_page(page, pattern)

        # ── Phase 5: Wait for manual CAPTCHA ──
        if not key:
            _progress("Waiting for CAPTCHA or manual sign-in in Chrome")
            for _ in range(12):
                _safe_wait(page, 5000)
                key = _extract_key_from_page(page, pattern)
                if key:
                    break

        if key:
            _hunt_log(f"SUCCESS: got key {mask_secret(key)}")
            _safe_wait(page, 1500)
            return key

        _hunt_log("INCOMPLETE: Chrome left open for manual finish")
        keep_open = True
        return None

    except Exception as exc:
        _hunt_log(f"ERROR: {exc}")
        keep_open = True
        return None

    finally:
        if keep_open and context:
            _hold_browser(manager, pw, context)
        elif context:
            try:
                context.close()
            except Exception:
                pass
            try:
                manager.__exit__(None, None, None)
            except Exception:
                pass
        else:
            try:
                manager.__exit__(None, None, None)
            except Exception:
                pass

# ── URL-based fetch ──────────────────────────────────────

def _fetch_from_url(url: str, email: str, password: str, *, write_env: bool = False) -> str:
    """Fetch API key from a direct URL the user provided."""
    _hunt_log(f"URL hunt: {url}")

    pid = detect_provider_from_url(url)
    if pid:
        cfg = PROVIDERS[pid]
        pattern = re.compile(cfg["pattern"])
    else:
        pattern = _GENERIC_KEY_PATTERN

    from playwright.sync_api import sync_playwright

    CHROME_PROFILE.mkdir(parents=True, exist_ok=True)
    _release_browser()
    _unlock_chrome_profile()

    manager = sync_playwright()
    pw = manager.__enter__()
    context = None

    try:
        context = _launch_persistent(pw, channel="chrome")

        page = context.pages[0] if context.pages else context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        _safe_wait(page, 3000)

        # If it's a login page, try signing in
        if _is_login_url(page.url):
            outcome = _do_login(page, email, password, pid or "unknown")
            if outcome != "ok":
                _progress(_login_fail_message(pid or "unknown", outcome))
            _wait_logged_in(page, timeout_sec=60)
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            _safe_wait(page, 3000)

        _click_any(page, [
            "Create", "Create API key", "Create Key", "Generate",
            "New", "Add", "Reveal", "Show",
        ])
        _safe_wait(page, 3000)

        key = _extract_key_from_page(page, pattern)
        if not key:
            for _ in range(8):
                _safe_wait(page, 5000)
                key = _extract_key_from_page(page, pattern)
                if key:
                    break

        if key:
            _hunt_log(f"URL hunt SUCCESS: {mask_secret(key)}")
            env_key = PROVIDERS[pid]["env_key"] if pid else ""
            if pid:
                save_key(pid, key, env_key, write_env=write_env)
            msg = f"Got the API key from {url}, sir:\n\n{key}"
            if write_env and env_key:
                msg += f"\n\nSaved to .env as {env_key}."
            elif pid:
                msg += f"\n\n{_env_hint(pid)}"
            return msg

        _hold_browser(manager, pw, context)
        return f"Chrome is open on {url}, sir. I couldn't find a key automatically — check the page and try again."

    except Exception as exc:
        _hunt_log(f"URL hunt error: {exc}")
        if context:
            _hold_browser(manager, pw, context)
        return f"Error fetching from {url}: {exc}. Chrome is still open."


def _handle_existing_key(provider_id: str, key: str, text: str) -> str:
    """Chat-only by default; write .env only on explicit ask."""
    from jarvis.tools.api_intent import wants_env_save

    cfg = PROVIDERS.get(provider_id, {})
    env_key = cfg.get("env_key", f"{provider_id.upper()}_API_KEY")
    name = provider_id.upper()
    # Always keep registry for "already have" detection
    save_key(provider_id, key, env_key, write_env=False)

    if wants_env_save(text):
        written = write_key_to_env(provider_id, key, env_key)
        return (
            f"Saved your {name} API key to .env as {written or env_key}, sir:\n\n{key}"
        )

    return (
        f"You already have {name} key, sir:\n\n{key}\n\n"
        f"Say 'refresh {provider_id} api' for a new one. {_env_hint(provider_id)}"
    )


# ── Blocking fetch (called from subprocess) ──────────────

def _fetch_blocking(text: str) -> str:
    load_dotenv(ROOT / ".env", override=True)

    from jarvis.tools.api_intent import resolve_provider, wants_env_save
    from jarvis.tools.command_parse import extract_urls

    write_env = wants_env_save(text)

    # Check for direct URL input
    urls = extract_urls(text)
    if urls:
        email = get_user_email(text)
        password = get_user_password()
        if not email:
            return "JARVIS_EMAIL missing in .env, sir."
        if not password:
            return "JARVIS_PASSWORD missing in .env, sir."
        return _fetch_from_url(urls[0], email, password, write_env=write_env)

    provider_id = resolve_provider(text)
    if not provider_id:
        return (
            "Which AI service, sir? Say something like 'get me groq api key' or "
            "'get eleven labs api key'. You can also give me a direct URL like "
            "'get api key from https://console.groq.com/keys'."
        )

    cfg = PROVIDERS[provider_id]
    email = get_user_email(text)
    password = get_user_password()
    name = provider_id.upper()

    existing = get_key(provider_id)
    if existing and "again" not in normalize(text) and "refresh" not in normalize(text):
        return _handle_existing_key(provider_id, existing, text)

    if not _has_playwright():
        return "Run: pip install playwright && playwright install chrome"
    if not email:
        return "JARVIS_EMAIL missing in .env, sir."
    if not password:
        return "JARVIS_PASSWORD missing in .env, sir."

    try:
        key = _playwright_fetch(provider_id, email, password)
    except Exception as exc:
        _hunt_log(f"Hunt exception: {exc}")
        return f"Chrome is still open, sir. Error: {exc}. Finish sign-in, then say 'get {provider_id} api key' again."

    if key:
        save_key(provider_id, key, cfg["env_key"], write_env=write_env)
        return _format_key_result(name, key, cfg["env_key"], write_env)

    if _LAST_HUNT_NOTE:
        return _LAST_HUNT_NOTE

    return (
        f"Chrome is still open on {name}, sir. I signed in with {email} — "
        f"if you see a CAPTCHA, complete it. Then say 'get {provider_id} api key' again."
    )

# ── Background launcher ─────────────────────────────────

def _background_hunt(text: str) -> None:
    """Launch hunt in subprocess — Playwright needs its own process on Windows."""
    subprocess.Popen(
        [sys.executable, "-m", "jarvis.tools.hunt_worker", text],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )


def fetch_api_key(text: str) -> str:
    """Start hunt in background — Chrome stays open until sign-in + key grab.

    Default: key is shown in chat only (registry kept for reuse).
    .env is written only when the user explicitly asks to save/post to env.
    """
    from jarvis.tools.api_intent import resolve_provider, wants_env_save
    from jarvis.tools.command_parse import extract_urls

    # Direct URL?
    urls = extract_urls(text)
    has_url = bool(urls)
    name = "API"

    if not has_url:
        provider_id = resolve_provider(text)
        if not provider_id:
            # Save-to-env with no resolvable provider
            if wants_env_save(text):
                return (
                    "Which key should I save to .env, sir? "
                    "Say 'save groq api to .env' (or get the key first)."
                )
            return (
                "Which AI service, sir? Say the name — like 'get me groq api key' or "
                "'get eleven labs api key'. Or give me a URL: 'get api from https://...'."
            )

        name = provider_id.upper()
        existing = get_key(provider_id)
        if existing and "again" not in normalize(text) and "refresh" not in normalize(text):
            # Instant path: show full key in chat; write .env only if asked
            return _handle_existing_key(provider_id, existing, text)

        # Explicit save-only with no key yet → still hunt, then write env
        if wants_env_save(text) and not existing:
            pass  # fall through to hunt with write_env gated in worker

    if not set_running(text):
        return "Already fetching an API key, sir. Watch Chrome — I'll post the result when ready."

    thread = threading.Thread(target=_background_hunt, args=(text,), daemon=True, name="api-hunt-launcher")
    thread.start()

    if has_url:
        return f"On it, sir. Opening {urls[0]} in Chrome to grab the API key."
    env_note = " I'll save it to .env when ready." if wants_env_save(text) else " I'll paste the API key here when ready."
    return (
        f"On it, sir. Chrome is opening {name} — signing in with your email now. "
        f"Do not close the browser.{env_note}"
    )
