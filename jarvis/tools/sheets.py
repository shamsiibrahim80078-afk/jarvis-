"""Google Sheets — open, read public sheets, check API registry."""

from __future__ import annotations

import csv
import io
import os
import re
from pathlib import Path
from urllib.parse import quote

import requests

from jarvis.tools import system
from jarvis.tools.workflows import get_link

ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = ROOT / ".env"


def _sheet_id(url: str) -> str | None:
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
    return m.group(1) if m else None


def open_google_sheet(url: str | None = None) -> str:
    from jarvis.context import set_context
    from jarvis.tools.api_registry import set_sheet_url
    from jarvis.tools.workflows import set_link

    target = url or get_link("api_sheet") or get_link("google_sheets") or "https://sheets.google.com"
    # Remember real sheet links so later "how many apis" / paste work without re-pasting
    if url and _sheet_id(url):
        set_link("api_sheet", url)
        set_sheet_url(url)
    set_context("sheet", sheet_url=target)
    system.open_in_chrome(target)
    return "Opening your Google Sheet, sir."


def navigate_sheet_tab(tab_name: str, sheet_url: str | None = None) -> str:
    """Go to a named tab in the saved Google Sheet — NOT a Google search."""
    from jarvis.context import set_context
    from jarvis.tools.workflows import get_sheet_tab_gid

    url = (sheet_url or "").strip() or get_link("api_sheet")
    if not url:
        return (
            "No sheet saved yet, sir. Paste the Google Sheets link once - "
            "say 'remember my api sheet is [url]', then ask me to open the tab."
        )

    # Never treat a tab name as a URL. Only real Sheets links are valid.
    sid = _sheet_id(url)
    if not sid:
        return (
            "That saved sheet link doesn't look like a Google Sheets URL, sir. "
            "Say 'remember my api sheet is [paste the full docs.google.com link]'."
        )

    display = tab_name.strip() or "APIs"
    gid = get_sheet_tab_gid(tab_name)
    if gid:
        tab_url = f"https://docs.google.com/spreadsheets/d/{sid}/edit#gid={gid}"
        set_context("sheet", sheet_url=url)
        system.open_in_chrome(tab_url)
        return f"Opening '{display}' tab in your sheet, sir."

    # No gid configured — still open the sheet and look for the tab
    tab_url = f"https://docs.google.com/spreadsheets/d/{sid}/edit"
    set_context("sheet", sheet_url=url)
    system.open_in_chrome(tab_url)
    return (
        f"Opened your sheet, looking for the {display} tab, sir. "
        f"If it doesn't land there, right-click the tab, copy link, and say: "
        f"'remember tab {display} gid is [number from URL]'."
    )


def fetch_sheet_csv(url: str, gid: str | None = None) -> str | None:
    """Fetch Google Sheet as CSV text (public/link-shared). Fail-fast with cache fallback."""
    sid = _sheet_id(url)
    if not sid:
        return None

    # Prefer explicit gid from URL or argument
    if not gid:
        m = re.search(r"[#&?]gid=(\d+)", url)
        if m:
            gid = m.group(1)

    cache_key = f"{sid}_{gid}" if gid else sid
    cache_path = ROOT / "data" / f"sheet_cache_{cache_key}.csv"

    def _ok(text: str) -> bool:
        return bool(text) and "," in text and "<html" not in text[:200].lower()

    candidates: list[str] = []
    if gid:
        candidates.append(f"https://docs.google.com/spreadsheets/d/{sid}/export?format=csv&gid={gid}")
    else:
        candidates.append(f"https://docs.google.com/spreadsheets/d/{sid}/export?format=csv")
        # One saved tab gid max (avoid long hang loops) when no explicit gid
        try:
            from jarvis.tools.workflows import _load
            for tab_gid in (_load().get("sheet_tabs") or {}).values():
                g = str(tab_gid or "").strip()
                if g.isdigit():
                    candidates.append(
                        f"https://docs.google.com/spreadsheets/d/{sid}/export?format=csv&gid={g}"
                    )
                    break
        except Exception:
            pass

    seen: set[str] = set()
    for export_url in candidates[:3]:
        if export_url in seen:
            continue
        seen.add(export_url)
        try:
            r = requests.get(export_url, timeout=12)
            if r.status_code == 200 and _ok(r.text):
                try:
                    cache_path.write_text(r.text, encoding="utf-8")
                except OSError:
                    pass
                return r.text
        except requests.RequestException:
            continue

    # Instant fallback: previous successful CSV for THIS gid only
    try:
        if cache_path.exists():
            cached = cache_path.read_text(encoding="utf-8")
            if _ok(cached):
                return cached
    except OSError:
        pass
    return None


def looks_like_api_table(header: list[str]) -> bool:
    """True if header looks like Provider/Name + Key columns (not a metric summary)."""
    h = [c.lower().strip() for c in header]
    # Summary sheets often use Metric/Count
    if any(c in ("metric", "count", "summary") for c in h):
        return False
    has_name = any(
        c in ("provider", "name", "service", "api", "site", "platform") or "provider" in c
        for c in h
    )
    has_key = any(("key" in c or "token" in c) and "env" not in c for c in h)
    # Credentials tabs sometimes corrupt the first header cell but keep "API Key / Token"
    if has_key:
        return True
    return has_name


def looks_like_summary_sheet(header: list[str], rows: list[list[str]] | None = None) -> bool:
    h = [c.lower().strip() for c in (header or [])]
    if any(c in ("metric", "count") for c in h):
        return True
    if rows and len(rows) < 20:
        joined = " ".join(" ".join(r).lower() for r in rows[:5])
        if "total providers" in joined or ("metric" in joined and "count" in joined):
            return True
    return False


def sheet_url_with_gid(url: str, gid: str | None) -> str:
    sid = _sheet_id(url)
    if not sid:
        return url
    if gid and str(gid).isdigit():
        return f"https://docs.google.com/spreadsheets/d/{sid}/edit#gid={gid}"
    return f"https://docs.google.com/spreadsheets/d/{sid}/edit"


def list_spreadsheet_gids(url: str) -> list[str]:
    """Discover tab gids from public htmlview (no Google API)."""
    sid = _sheet_id(url)
    if not sid:
        return []
    try:
        r = requests.get(
            f"https://docs.google.com/spreadsheets/d/{sid}/htmlview",
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0 Jarvis/1.0"},
        )
        if r.status_code != 200:
            return []
        return sorted(set(re.findall(r"gid[=:\\\"']+(\d+)", r.text)))
    except requests.RequestException:
        return []


def classify_sheet_tab(header: list[str], rows: list[list[str]]) -> str:
    """credentials | catalog | summary | tracker | other"""
    if looks_like_summary_sheet(header, rows):
        return "summary"
    h = [c.lower().strip() for c in header]
    has_key = any(("key" in c or "token" in c) and "env" not in c for c in h)
    has_website = any(c in ("website", "url", "link", "signup", "sign up") or "website" in c for c in h)
    has_provider = any("provider" in c or c in ("name", "service", "api") for c in h)
    # Classify: skip tiny "lookup" title sheets as paste targets
    title = (header[0] if header else "").lower()
    if "lookup" in title and len(rows) < 50:
        return "tracker"
    if "phantom" in title and "tracker" in title:
        return "tracker"
    if "credential" in title and "lookup" not in title:
        return "credentials"
    if has_key and (has_provider or len(rows) > 50):
        # Credentials: key near the left. Catalog: Provider + Website + key farther right.
        key_i = next((i for i, c in enumerate(h) if ("key" in c or "token" in c) and "env" not in c), 99)
        if has_website and key_i > 2:
            return "catalog"
        return "credentials"
    if has_provider and has_website and not has_key:
        return "catalog"
    if has_provider and len(rows) > 50:
        return "catalog"
    return "other"


def discover_sheet_tabs(url: str, force: bool = False) -> list[dict]:
    """Probe spreadsheet tabs; cache results. Never treat summary as paste target."""
    import json

    sid = _sheet_id(url)
    if not sid:
        return []

    cache_path = ROOT / "data" / f"sheet_tabs_{sid}.json"
    if not force and cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(cached, list) and cached:
                return cached
        except (json.JSONDecodeError, OSError):
            pass

    found: list[dict] = []
    for gid in list_spreadsheet_gids(url):
        csv_text = fetch_sheet_csv(url, gid=gid)
        if not csv_text:
            continue
        reader = csv.reader(io.StringIO(csv_text))
        all_rows = list(reader)
        if not all_rows:
            continue
        header, data = all_rows[0], all_rows[1:]
        kind = classify_sheet_tab(header, data)
        title = (header[0] or "").strip()[:80]
        found.append({
            "gid": gid,
            "kind": kind,
            "title": title,
            "rows": len(data),
            "header": header[:8],
        })
        try:
            from jarvis.tools.workflows import set_sheet_tab
            if kind == "credentials":
                set_sheet_tab("phantom credentials", gid)
                set_sheet_tab("phantom api tools", gid)
                set_sheet_tab("api credentials", gid)
            elif kind == "catalog":
                set_sheet_tab("phantom providers", gid)
                set_sheet_tab("api catalog", gid)
            elif kind == "tracker" or "phantom" in title.lower():
                set_sheet_tab("phantom tracker", gid)
        except Exception:
            pass

    try:
        cache_path.write_text(json.dumps(found, indent=2), encoding="utf-8")
    except OSError:
        pass
    return found


def resolve_best_tab(
    url: str,
    hint: str = "",
    prefer: str = "credentials",
) -> dict | None:
    """Pick credentials/catalog tab from hint (e.g. phantom) or preference."""
    from jarvis.tools.workflows import get_sheet_tab_gid

    hint_l = (hint or "").lower().strip()

    # Prefer explicitly saved gids (fast, no rediscovery)
    saved_names = []
    if prefer == "credentials":
        saved_names = [
            hint_l,
            "phantom api tools",
            "phantom credentials",
            "api credentials",
        ]
    elif prefer == "catalog":
        saved_names = [hint_l, "phantom providers", "api catalog"]
    else:
        saved_names = [hint_l]

    for name in saved_names:
        if not name:
            continue
        gid = get_sheet_tab_gid(name)
        if gid:
            csv_text = fetch_sheet_csv(url, gid=gid)
            if csv_text:
                reader = csv.reader(io.StringIO(csv_text))
                all_rows = list(reader)
                if all_rows:
                    header, data = all_rows[0], all_rows[1:]
                    kind = classify_sheet_tab(header, data)
                    if kind == "summary":
                        continue
                    return {
                        "gid": gid,
                        "kind": kind if kind != "other" else prefer,
                        "title": (header[0] or name)[:80],
                        "rows": len(data),
                        "header": header[:8],
                    }
            # Even if CSV temporarily fails, trust saved credentials gid
            if prefer == "credentials" and name in (
                "phantom api tools",
                "phantom credentials",
                "api credentials",
            ):
                return {
                    "gid": gid,
                    "kind": "credentials",
                    "title": name,
                    "rows": 0,
                    "header": [],
                }

    tabs = discover_sheet_tabs(url)
    if not tabs:
        return None

    if hint_l:
        scored: list[tuple[int, dict]] = []
        for t in tabs:
            score = 0
            blob = f"{t.get('title', '')} {t.get('kind', '')}".lower()
            if hint_l in blob:
                score += 5
            if "phantom" in hint_l and (
                "phantom" in blob or t.get("kind") in ("credentials", "catalog", "tracker")
            ):
                score += 3
            if t.get("kind") == prefer:
                score += 4
            if t.get("kind") == "summary":
                score -= 10
            # Prefer real key tables (many rows) over tiny lookup sheets
            rows = int(t.get("rows") or 0)
            if rows >= 100:
                score += 5
            elif rows < 40 and t.get("kind") == "credentials":
                score -= 2
            scored.append((score, t))
        scored.sort(key=lambda x: (-x[0], -int(x[1].get("rows") or 0)))
        if scored and scored[0][0] > 0:
            return scored[0][1]

    preferred = [t for t in tabs if t.get("kind") == prefer]
    if preferred:
        return max(preferred, key=lambda t: int(t.get("rows") or 0))
    catalog = [t for t in tabs if t.get("kind") == "catalog"]
    if catalog:
        return max(catalog, key=lambda t: int(t.get("rows") or 0))
    usable = [t for t in tabs if t.get("kind") not in ("summary", "other")]
    return max(usable, key=lambda t: int(t.get("rows") or 0)) if usable else None


def parse_summary_metrics(csv_text: str) -> dict[str, int]:
    """Parse Metric,Count style summary tabs into a dict of ints."""
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)
    metrics: dict[str, int] = {}
    for row in rows:
        if len(row) < 2:
            continue
        name = row[0].strip().lower()
        val = row[1].strip().replace(",", "")
        if not name or not val.isdigit():
            continue
        metrics[name] = int(val)
    return metrics



def _read_env_keys() -> dict[str, str]:
    keys: dict[str, str] = {}
    if not ENV_PATH.exists():
        return keys
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("=")
            if v.strip():
                keys[k.strip()] = v.strip()[:8] + "..."
    return keys


def check_apis(sheet_url: str | None = None) -> str:
    """Check APIs from sheet + local .env."""
    url = sheet_url or get_link("api_sheet")
    env_keys = _read_env_keys()
    lines = ["API status, sir:"]

    if env_keys:
        lines.append("Local .env:")
        for k, preview in env_keys.items():
            if "KEY" in k.upper() or "API" in k.upper():
                lines.append(f"  OK {k} = {preview}")
    else:
        lines.append("No API keys in .env yet.")

    if url:
        csv_text = fetch_sheet_csv(url)
        if csv_text:
            reader = csv.reader(io.StringIO(csv_text))
            rows = list(reader)[:20]
            lines.append(f"\nFrom your sheet ({len(rows)} rows):")
            for row in rows[:10]:
                if row and any(cell.strip() for cell in row):
                    lines.append("  • " + " | ".join(cell.strip() for cell in row if cell.strip()))
        else:
            open_google_sheet(url)
            lines.append(
                f"\nOpened your sheet in Chrome. "
                f"If it's private, sign in — or share it as 'Anyone with link' for auto-read."
            )
    else:
        lines.append(
            "\nNo API sheet saved yet. Say: "
            "'remember my api sheet is [paste your Google Sheets link]'"
        )

    return "\n".join(lines)


def sync_apis_to_env(sheet_url: str | None = None) -> str:
    """Read sheet rows (Provider, Key) and write missing keys to .env."""
    url = sheet_url or get_link("api_sheet")
    if not url:
        return "No API sheet configured, sir. Give me the Google Sheets link first."

    csv_text = fetch_sheet_csv(url)
    if not csv_text:
        open_google_sheet(url)
        return "Sheet is private or unreachable. Opened in Chrome — sign in, then try again."

    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)
    if not rows:
        return "Sheet appears empty, sir."

    # Expect header row: provider/name | key | env_var (optional)
    header = [c.lower().strip() for c in rows[0]]
    name_idx = next((i for i, c in enumerate(header) if c in ("provider", "name", "service", "api")), 0)
    key_idx = next((i for i, c in enumerate(header) if "key" in c), 1)
    env_idx = next((i for i, c in enumerate(header) if "env" in c), -1)

    env_map = {
        "groq": "GROQ_API_KEY",
        "fish": "FISH_AUDIO_API_KEY",
        "fish audio": "FISH_AUDIO_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "nvidia": "NVIDIA_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "elevenlabs": "ELEVENLABS_API_KEY",
    }

    updated = 0
    env_lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    existing = {ln.split("=")[0] for ln in env_lines if "=" in ln}

    for row in rows[1:]:
        if len(row) <= max(name_idx, key_idx):
            continue
        provider = row[name_idx].strip().lower()
        key_val = row[key_idx].strip()
        if not key_val or len(key_val) < 10:
            continue
        env_key = row[env_idx].strip() if env_idx >= 0 and env_idx < len(row) else env_map.get(provider, "")
        if not env_key:
            env_key = f"{provider.upper().replace(' ', '_')}_API_KEY"
        if env_key in existing:
            continue
        env_lines.append(f"{env_key}={key_val}")
        existing.add(env_key)
        updated += 1

    if updated:
        ENV_PATH.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
        return f"Synced {updated} API key(s) from your sheet to .env, sir."

    return "No new keys to sync, sir. Keys may already be in .env or sheet format needs Provider | Key columns."
