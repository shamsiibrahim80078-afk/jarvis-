"""Batch API pipeline — read sheet → fetch each key → paste back into sheet."""

from __future__ import annotations

import csv
import io
import logging
import re
import time
from pathlib import Path

from jarvis.tools.api_hunter import (
    PROVIDERS, _fetch_blocking, _has_playwright, detect_provider,
    detect_provider_from_url, fetch_api_key,
)
from jarvis.tools.api_intent import wants_env_save
from jarvis.tools.api_registry import export_summary, get_key, save_key, set_sheet_url
from jarvis.tools.command_parse import extract_urls, normalize
from jarvis.tools.credentials import get_user_email, get_user_password
from jarvis.tools.sheets import (
    discover_sheet_tabs,
    fetch_sheet_csv,
    looks_like_api_table,
    open_google_sheet,
    parse_summary_metrics,
    resolve_best_tab,
    sheet_url_with_gid,
    _sheet_id,
)
from jarvis.tools.workflows import get_link, set_link, set_sheet_tab

logger = logging.getLogger("jarvis.api_pipeline")
ROOT = Path(__file__).resolve().parents[2]
EXPORT_PATH = ROOT / "data" / "apis_filled.csv"
LOG_PATH = ROOT / "data" / "batch_pipeline.log"

# Map sheet provider names → our provider ids
NAME_MAP: dict[str, str] = {}
for pid, cfg in PROVIDERS.items():
    for n in cfg["names"]:
        NAME_MAP[n] = pid


def _log(msg: str) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass
    logger.info(msg)


def _resolve_provider(name: str) -> str | None:
    lower = name.lower().strip()
    if lower in PROVIDERS:
        return lower
    if lower in NAME_MAP:
        return NAME_MAP[lower]
    # Longest name first — word/prefix match, never "groq" inside "ngrok"
    candidates: list[tuple[int, str, str]] = []
    for pid, cfg in PROVIDERS.items():
        for n in cfg["names"]:
            n = n.lower().strip()
            if n:
                candidates.append((len(n), n, pid))
    candidates.sort(reverse=True)
    for _, n, pid in candidates:
        if lower == n or lower.startswith(n + " ") or lower.startswith(n + "-"):
            return pid
        if re.search(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])", lower):
            return pid
        # CamelCase / glued: GroqCloud, OpenAI
        if lower.startswith(n) and len(n) >= 4:
            return pid
    return detect_provider(name)


def _parse_sheet_rows(csv_text: str) -> tuple[list[str], list[list[str]]]:
    """Returns (header, data_rows) — preserves original row structure for paste-back."""
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)
    if not rows:
        return [], []
    return rows[0], rows[1:]


def _find_columns(header: list[str]) -> dict[str, int]:
    """Find relevant column indexes from header row."""
    h = [c.lower().strip() for c in header]
    cols: dict[str, int] = {}

    # Provider / name column
    for i, c in enumerate(h):
        if c in ("provider", "name", "service", "api", "site", "platform"):
            cols["name"] = i
            break
    if "name" not in cols:
        # Credentials tabs may have a corrupted header[0] — still use col A for names
        cols["name"] = 0

    # Key column — prefer "API Key / Token"
    for i, c in enumerate(h):
        if "api key" in c or c in ("key", "token") or ("key" in c and "env" not in c):
            cols["key"] = i
            break
    if "key" not in cols:
        for i, c in enumerate(h):
            if "token" in c:
                cols["key"] = i
                break

    # URL column
    for i, c in enumerate(h):
        if c in ("url", "link", "signup", "website", "sign up") or "website" in c:
            cols["url"] = i
            break

    # Env var column
    for i, c in enumerate(h):
        if "env" in c:
            cols["env"] = i
            break

    return cols


def parse_batch_scope(text: str) -> dict:
    """Parse tab hint + sheet row range from user command."""
    lower = normalize(text)
    scope: dict = {
        "tab_hint": "",
        "start_row": None,
        "end_row": None,
        "limit": None,
        "do_paste": any(w in lower for w in ("paste", "fill", "put", "write")),
        "auto_paste": True,  # scoped get+paste is the intended UX
    }

    # "from 1590 to the end" / "from row 1590 till end" / "rows 1590-1700"
    m = re.search(
        r"(?:from|starting(?:\s+at)?|start(?:ing)?(?:\s+from)?)\s+(?:row\s+)?(\d+)\s*"
        r"(?:to|till|until|-|–)\s*(?:the\s+)?(?:end|last|(\d+))",
        lower,
    )
    if m:
        scope["start_row"] = int(m.group(1))
        if m.group(2):
            scope["end_row"] = int(m.group(2))
    else:
        m = re.search(r"\brows?\s+(\d+)\s*[-–]\s*(\d+)", lower)
        if m:
            scope["start_row"] = int(m.group(1))
            scope["end_row"] = int(m.group(2))
        else:
            m = re.search(r"(?:from|starting(?:\s+at)?)\s+(?:row\s+)?(\d+)\b", lower)
            if m:
                scope["start_row"] = int(m.group(1))

    m = re.search(r"\bfirst\s+(\d+)\b", lower)
    if m:
        scope["limit"] = int(m.group(1))

    # Tab / section hints
    m = re.search(
        r"(?:get|fetch|grab|fill|paste)\s+(?:me\s+)?(?:the\s+)?"
        r"(.+?)\s+apis?(?:\s+from|\s+in|\s+on|\s*$)",
        lower,
    )
    if m:
        hint = m.group(1).strip()
        hint = re.sub(r"^(all|missing|empty|remaining)\s+", "", hint).strip()
        if hint and hint not in ("all", "the", "my", "sheet", "google sheet"):
            scope["tab_hint"] = hint

    if not scope["tab_hint"]:
        if "phantom" in lower:
            scope["tab_hint"] = "phantom api tools"
        elif "veridiq" in lower or "veriq" in lower:
            scope["tab_hint"] = "veridiq apis"

    # Explicit paste-only commands should not auto-fetch
    if re.search(r"^\s*paste\b", lower) or "paste apis" in lower or "paste api" in lower:
        if "get" not in lower and "fetch" not in lower:
            scope["auto_paste"] = False

    return scope


def _catalog_urls_by_name(sheet_url: str) -> dict[str, str]:
    """Map provider name → website URL from the catalog tab."""
    tab = resolve_best_tab(sheet_url, hint="phantom providers", prefer="catalog")
    if not tab:
        return {}
    csv_text = fetch_sheet_csv(sheet_url, gid=tab["gid"])
    if not csv_text:
        return {}
    header, rows = _parse_sheet_rows(csv_text)
    cols = _find_columns(header)
    name_i = cols.get("name", 0)
    url_i = cols.get("url", -1)
    out: dict[str, str] = {}
    if url_i < 0:
        return out
    for row in rows:
        name = row[name_i].strip() if name_i < len(row) else ""
        link = row[url_i].strip() if url_i < len(row) else ""
        if name and link.startswith("http"):
            out[name.lower()] = link
    return out


def _iter_scoped_rows(
    data_rows: list[list[str]],
    start_row: int | None,
    end_row: int | None,
) -> list[tuple[int, int, list[str]]]:
    """Yield (data_idx, sheet_row, row). sheet_row is 1-based with header on row 1."""
    out: list[tuple[int, int, list[str]]] = []
    max_sheet_row = len(data_rows) + 1
    start = int(start_row) if start_row else 2
    end = int(end_row) if end_row else max_sheet_row
    start = max(2, start)
    end = min(end, max_sheet_row)
    for sheet_row in range(start, end + 1):
        data_idx = sheet_row - 2
        if 0 <= data_idx < len(data_rows):
            out.append((data_idx, sheet_row, data_rows[data_idx]))
    return out


def _extract_key_from_result(result: str) -> str | None:
    """Pull actual key out of Jarvis response text."""
    patterns = [
        r"gsk_[A-Za-z0-9]+",
        r"sk-ant-[A-Za-z0-9_-]+",
        r"sk-or-[A-Za-z0-9_-]+",
        r"sk_[a-f0-9]+",
        r"sk-[A-Za-z0-9_-]+",
        r"AIza[A-Za-z0-9_-]+",
        r"nvapi-[A-Za-z0-9_-]+",
        r"hf_[A-Za-z0-9]+",
    ]
    for pat in patterns:
        m = re.search(pat, result)
        if m:
            return m.group(0)
    return None


def _paste_keys_to_sheet(sheet_url: str, results: list[dict]) -> str:
    """Use Playwright to open the CORRECT tab and paste keys into exact cells."""
    if not _has_playwright():
        return "Playwright not installed — can't paste into sheet."

    from jarvis.tools.api_hunter import (
        CHROME_PROFILE, _hold_browser, _release_browser, _safe_wait,
    )
    from playwright.sync_api import sync_playwright

    pasteable = [r for r in results if r.get("key") and r.get("status") == "fetched"]
    if not pasteable:
        return "No new keys to paste into sheet."

    # Prefer credentials gid from results; never paste onto summary
    gid = next((str(r.get("gid")) for r in pasteable if r.get("gid")), None)
    if not gid:
        tab = resolve_best_tab(sheet_url, prefer="credentials")
        gid = tab["gid"] if tab else None
    target_url = sheet_url_with_gid(sheet_url, gid)

    _log(f"Pasting {len(pasteable)} keys into {target_url}")
    CHROME_PROFILE.mkdir(parents=True, exist_ok=True)
    _release_browser()

    manager = sync_playwright()
    pw = manager.__enter__()
    context = None

    try:
        try:
            context = pw.chromium.launch_persistent_context(
                str(CHROME_PROFILE), channel="chrome", headless=False,
                slow_mo=120, viewport={"width": 1280, "height": 900},
                args=["--disable-blink-features=AutomationControlled", "--no-first-run"],
            )
        except Exception:
            context = pw.chromium.launch_persistent_context(
                str(CHROME_PROFILE), headless=False,
                slow_mo=120, viewport={"width": 1280, "height": 900},
            )

        page = context.pages[0] if context.pages else context.new_page()
        page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
        _safe_wait(page, 5000)

        pasted = 0
        for meta in pasteable:
            try:
                key = meta["key"]
                name = (meta.get("name") or "").strip()
                key_col = int(meta.get("key_col", 1) or 1)
                if key_col < 0:
                    key_col = 1
                sheet_row = meta.get("sheet_row")
                if sheet_row is None and meta.get("row_idx") is not None and int(meta["row_idx"]) >= 0:
                    sheet_row = int(meta["row_idx"]) + 2

                if sheet_row is not None and int(sheet_row) >= 2:
                    col_letter = chr(ord("A") + key_col)
                    cell_ref = f"{col_letter}{int(sheet_row)}"
                    name_box = page.locator('[aria-label="Name Box"]').first
                    if not name_box.is_visible(timeout=3000):
                        name_box = page.locator('#t-name-box').first
                    try:
                        name_box.click(timeout=3000)
                        _safe_wait(page, 300)
                        name_box.fill(cell_ref, timeout=3000)
                        page.keyboard.press("Enter")
                        _safe_wait(page, 800)
                    except Exception:
                        page.keyboard.press("Control+g")
                        _safe_wait(page, 500)
                        page.keyboard.type(cell_ref, delay=20)
                        page.keyboard.press("Enter")
                        _safe_wait(page, 800)
                elif name:
                    page.keyboard.press("Control+f")
                    _safe_wait(page, 600)
                    page.keyboard.type(name, delay=20)
                    _safe_wait(page, 800)
                    page.keyboard.press("Enter")
                    _safe_wait(page, 600)
                    page.keyboard.press("Escape")
                    _safe_wait(page, 400)
                    for _ in range(max(key_col, 1)):
                        page.keyboard.press("ArrowRight")
                        _safe_wait(page, 150)
                else:
                    continue

                # Clear existing cell then type
                page.keyboard.press("Delete")
                _safe_wait(page, 200)
                page.keyboard.type(key, delay=15)
                page.keyboard.press("Enter")
                _safe_wait(page, 500)
                pasted += 1
                _log(f"Pasted key for {name or sheet_row} → col {key_col} row {sheet_row}")
            except Exception as exc:
                _log(f"Failed to paste {meta.get('name')}: {exc}")

        _safe_wait(page, 2000)
        _hold_browser(manager, pw, context)
        return (
            f"Pasted {pasted}/{len(pasteable)} keys into the credentials tab "
            f"(gid={gid}), sir. Chrome is still open — verify the values."
        )

    except Exception as exc:
        _log(f"Sheet paste error: {exc}")
        if context:
            _hold_browser(manager, pw, context)
        return f"Error pasting into sheet: {exc}. Chrome is still open."


def run_batch_from_sheet(text: str) -> str:
    """Detect API section → scoped rows → fetch each key → paste on the matching row."""
    sheet_url = _resolve_sheet_url(text)
    if not sheet_url:
        return "No sheet link, sir. Say 'go to this sheet [URL] and get all apis' or paste the link."

    set_link("api_sheet", sheet_url)
    set_sheet_url(sheet_url)
    scope = parse_batch_scope(text)
    _log(f"Batch scoped: {scope} url={sheet_url}")

    # Prefer saved credentials gid — skip slow rediscovery when possible
    cred = resolve_best_tab(sheet_url, hint=scope.get("tab_hint") or "phantom", prefer="credentials")
    if not cred:
        discover_sheet_tabs(sheet_url)
        cred = resolve_best_tab(sheet_url, hint=scope.get("tab_hint") or "phantom", prefer="credentials")
    if not cred:
        open_google_sheet(sheet_url)
        return (
            "Couldn't find the API credentials tab, sir. "
            "I opened the sheet — say 'remember tab phantom api tools gid is [number]'."
        )

    gid = cred["gid"]
    set_sheet_tab("phantom api tools", gid)
    target_url = sheet_url_with_gid(sheet_url, gid)
    csv_text = fetch_sheet_csv(sheet_url, gid=gid)
    if not csv_text:
        open_google_sheet(target_url)
        return (
            "Credentials tab is private, sir. I opened it in Chrome. "
            "Share as 'Anyone with the link can view', then retry."
        )

    header, data_rows = _parse_sheet_rows(csv_text)
    cols = _find_columns(header)
    if not data_rows:
        return "Credentials tab is empty, sir."

    max_sheet_row = len(data_rows) + 1
    start_row = scope.get("start_row")
    end_row = scope.get("end_row")

    if start_row and start_row > max_sheet_row:
        return (
            f"Row {start_row} is past the end of the credentials tab, sir. "
            f"That tab only has rows 2–{max_sheet_row} "
            f"({cred.get('rows')} APIs, gid={gid}). "
            f"Say e.g. 'get phantom apis from 150 to the end and paste'."
        )

    scoped = _iter_scoped_rows(data_rows, start_row, end_row)
    if scope.get("limit"):
        scoped = scoped[: int(scope["limit"])]

    # If no explicit range, default to missing-key rows only (cap 50 unless scoped)
    name_idx = cols.get("name", 0)
    key_idx = cols.get("key", 1)
    url_idx = cols.get("url", -1)
    env_idx = cols.get("env", -1)

    if start_row is None and end_row is None and not scope.get("limit"):
        missing = []
        for data_idx, sheet_row, row in _iter_scoped_rows(data_rows, 2, max_sheet_row):
            name = row[name_idx].strip() if name_idx < len(row) else ""
            if not name or len(name) > 120:
                continue
            existing = row[key_idx].strip() if key_idx >= 0 and key_idx < len(row) else ""
            if existing and len(existing) > 10:
                continue
            missing.append((data_idx, sheet_row, row))
            if len(missing) >= 50:
                break
        scoped = missing

    catalog_urls = _catalog_urls_by_name(sheet_url)
    write_env = wants_env_save(text)

    fetched = 0
    skipped = 0
    failed: list[str] = []
    results: list[dict] = []

    for data_idx, sheet_row, row in scoped:
        name = row[name_idx].strip() if name_idx < len(row) else ""
        if not name or len(name) > 120:
            continue
        # Skip header-like / garbage name cells
        if name.lower() in ("provider", "name", "api key / token", "metric"):
            continue

        existing_key = row[key_idx].strip() if key_idx >= 0 and key_idx < len(row) else ""
        row_url = row[url_idx].strip() if url_idx >= 0 and url_idx < len(row) else ""
        if not row_url:
            row_url = catalog_urls.get(name.lower(), "")
        env_var = row[env_idx].strip() if env_idx >= 0 and env_idx < len(row) else ""

        pid = _resolve_provider(name)
        if not pid and row_url:
            pid = detect_provider_from_url(row_url)
        if not pid:
            _log(f"Unknown provider: {name} @ row {sheet_row}")
            failed.append(f"{name}(r{sheet_row})")
            results.append({
                "name": name, "key": "", "status": "unknown",
                "row_idx": data_idx, "sheet_row": sheet_row,
                "key_col": key_idx if key_idx >= 0 else 1, "gid": gid,
            })
            continue

        cfg = PROVIDERS.get(pid, {})
        if not env_var:
            env_var = cfg.get("env_key", f"{pid.upper()}_API_KEY")

        if existing_key and len(existing_key) > 10:
            skipped += 1
            results.append({
                "name": name, "key": existing_key, "status": "already_has_key",
                "row_idx": data_idx, "sheet_row": sheet_row,
                "key_col": key_idx if key_idx >= 0 else 1, "gid": gid,
            })
            continue

        local_key = get_key(pid)
        if local_key:
            results.append({
                "name": name, "key": local_key, "status": "fetched",
                "row_idx": data_idx, "sheet_row": sheet_row,
                "key_col": key_idx if key_idx >= 0 else 1, "gid": gid,
            })
            fetched += 1
            continue

        _log(f"Fetching {pid} for sheet row {sheet_row}...")
        try:
            result_text = _fetch_blocking(f"get {pid} api key again")
            key = _extract_key_from_result(result_text)
            if key:
                save_key(pid, key, env_var, write_env=write_env)
                results.append({
                    "name": name, "key": key, "status": "fetched",
                    "row_idx": data_idx, "sheet_row": sheet_row,
                    "key_col": key_idx if key_idx >= 0 else 1, "gid": gid,
                })
                fetched += 1
            else:
                failed.append(f"{name}(r{sheet_row})")
                results.append({
                    "name": name, "key": "", "status": "needs_manual",
                    "row_idx": data_idx, "sheet_row": sheet_row,
                    "key_col": key_idx if key_idx >= 0 else 1, "gid": gid,
                })
        except Exception as exc:
            _log(f"Error fetching {pid}: {exc}")
            failed.append(f"{name}(r{sheet_row})")
            results.append({
                "name": name, "key": "", "status": str(exc)[:40],
                "row_idx": data_idx, "sheet_row": sheet_row,
                "key_col": key_idx if key_idx >= 0 else 1, "gid": gid,
            })

    _export_csv(results)

    paste_msg = ""
    should_paste = scope.get("do_paste") or scope.get("auto_paste")
    if fetched > 0 and key_idx >= 0 and should_paste:
        paste_msg = "\n" + _paste_keys_to_sheet(sheet_url, results)
    elif fetched > 0:
        paste_msg = f"\nSay 'paste apis into sheet' to write {fetched} keys into the credentials tab."

    range_desc = (
        f"rows {start_row or 2}–{end_row or max_sheet_row}"
        if start_row or end_row
        else "missing-key rows"
    )
    lines = [
        f"Scoped batch on credentials tab (gid={gid}), {range_desc}, sir.",
        f"Fetched {fetched}, skipped {skipped} (already had keys).",
    ]
    if write_env:
        lines.append("Fetched keys were also written to .env (you asked to save).")
    else:
        lines.append("Keys stay in chat/registry — say 'save X api to .env' if needed.")
    if failed:
        lines.append(f"Need attention: {', '.join(failed[:10])}")
    lines.append("Results saved to data/apis_filled.csv.")
    if paste_msg:
        lines.append(paste_msg.strip())
    lines.append(export_summary())
    return "\n".join(lines)


def paste_apis_to_sheet(text: str) -> str:
    """Paste previously fetched keys into the credentials tab at exact rows."""
    sheet_url = _resolve_sheet_url(text)
    if not sheet_url:
        return "No sheet saved, sir. Give me the sheet link first."

    urls = extract_urls(text)
    if urls:
        set_link("api_sheet", sheet_url)
        set_sheet_url(sheet_url)

    scope = parse_batch_scope(text)
    discover_sheet_tabs(sheet_url)
    cred = resolve_best_tab(sheet_url, hint=scope.get("tab_hint") or "phantom", prefer="credentials")
    gid = cred["gid"] if cred else None

    results: list[dict] = []

    # Prefer prior batch export (with sheet_row / gid when present)
    if EXPORT_PATH.exists():
        try:
            with EXPORT_PATH.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for i, row in enumerate(reader):
                    if row.get("key") and row.get("status") == "fetched":
                        sheet_row = row.get("sheet_row")
                        try:
                            sheet_row_i = int(sheet_row) if sheet_row else (i + 2)
                        except ValueError:
                            sheet_row_i = i + 2
                        key_col = 1
                        try:
                            key_col = int(row.get("key_col") or 1)
                        except ValueError:
                            key_col = 1
                        results.append({
                            "name": row.get("name", ""),
                            "key": row["key"],
                            "status": "fetched",
                            "row_idx": sheet_row_i - 2,
                            "sheet_row": sheet_row_i,
                            "key_col": key_col,
                            "gid": row.get("gid") or gid,
                        })
        except Exception as exc:
            _log(f"Error reading batch results: {exc}")

    # Fallback: match registry keys to empty credentials rows
    if not results and gid:
        csv_text = fetch_sheet_csv(sheet_url, gid=gid)
        if csv_text:
            header, data_rows = _parse_sheet_rows(csv_text)
            if looks_like_api_table(header) or True:
                cols = _find_columns(header)
                name_idx = cols.get("name", 0)
                key_idx = cols.get("key", 1)
                scoped = _iter_scoped_rows(
                    data_rows,
                    scope.get("start_row"),
                    scope.get("end_row"),
                )
                for data_idx, sheet_row, row in scoped:
                    name = row[name_idx].strip() if name_idx < len(row) else ""
                    if not name:
                        continue
                    existing = row[key_idx].strip() if key_idx < len(row) else ""
                    if existing and len(existing) > 8:
                        continue
                    pid = _resolve_provider(name)
                    if not pid:
                        continue
                    local_key = get_key(pid)
                    if local_key:
                        results.append({
                            "name": name,
                            "key": local_key,
                            "status": "fetched",
                            "row_idx": data_idx,
                            "sheet_row": sheet_row,
                            "key_col": key_idx if key_idx >= 0 else 1,
                            "gid": gid,
                        })

    if not results:
        return (
            "No keys to paste, sir. Fetch first — e.g. "
            "'get phantom apis from 150 to 160 and paste'."
        )

    return _paste_keys_to_sheet(sheet_url, results)


def _export_csv(results: list[dict]) -> None:
    if not results:
        return
    EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fields = ["name", "key", "status", "sheet_row", "key_col", "gid"]
    with EXPORT_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in results:
            w.writerow({k: r.get(k, "") for k in fields})


def is_batch_api_command(text: str) -> bool:
    lower = normalize(text)
    # Count / status questions are handled separately — never batch-fetch
    if is_api_count_command(text):
        return False
    # Single-provider hunt from a console URL is NOT a sheet batch
    # e.g. "get api from https://console.groq.com/keys"
    urls = extract_urls(text)
    if urls and "docs.google.com/spreadsheets" not in (urls[0] or "").lower():
        if re.search(r"\b(api\s*key|get\s+api|fetch\s+api|grab\s+api)\b", lower):
            try:
                from jarvis.tools.api_hunter import detect_provider, detect_provider_from_url
                if detect_provider(text) or detect_provider_from_url(urls[0]):
                    return False
            except Exception:
                pass
    triggers = (
        "get all api", "get all apis", "fetch all api", "batch api",
        "all apis from", "apis from sheet", "get apis from",
        "fill api sheet", "sync all api", "150 api",
        "paste api", "paste apis", "put apis",
        "go to this sheet", "go to the sheet", "open this sheet",
        "get phantom", "fetch phantom", "phantom api", "phantom apis",
    )
    if any(t in lower for t in triggers):
        return True
    # "get X apis from 1590" / "get ... apis from row N" / sheet / phantom
    # NOTE: bare "from" alone is too broad ("get api from https://console…")
    if re.search(r"\b(get|fetch|grab|fill)\b.+\bapis?\b", lower) and (
        "sheet" in lower
        or "phantom" in lower
        or "row" in lower
        or re.search(r"from\s+(?:row\s+)?\d+", lower)
    ):
        return True
    # "go to [URL] and get" / "open [URL] and get apis"
    if re.search(r"https?://docs\.google\.com/spreadsheets", text) and re.search(r"\b(api|key|get|fetch|grab)\b", lower):
        return True
    return False


def _resolve_sheet_url(text: str = "") -> str | None:
    """Saved api_sheet link, registry sheet_url, or URL in the command."""
    urls = extract_urls(text) if text else []
    if urls:
        return urls[0]
    url = get_link("api_sheet")
    if url:
        return url
    try:
        from jarvis.tools.api_registry import _load
        reg = (_load().get("sheet_url") or "").strip()
        if reg:
            return reg
    except Exception:
        pass
    return None


def is_api_count_command(text: str) -> bool:
    """True for 'how many apis left / remaining / missing' — never send to LLM."""
    lower = normalize(text)
    if not re.search(r"\bapis?\b", lower):
        return False
    # Don't steal hunt / batch fetch intents
    if re.search(r"\b(get|fetch|grab|sign\s*in|login)\b.{0,40}\b(api\s*key|key)\b", lower):
        return False
    if any(t in lower for t in ("get all api", "fetch all api", "paste api", "paste apis", "put apis")):
        return False

    patterns = (
        r"how\s+many\s+.{0,40}\bapis?\b",
        r"\bapis?\b.{0,40}\b(left|remaining|missing|still|empty|without)\b",
        r"\b(left|remaining|missing|still|empty)\b.{0,40}\bapis?\b",
        r"count\s+.{0,40}\bapis?\b",
        r"\bapis?\b.{0,20}\bcount\b",
        r"which\s+.{0,40}\bapis?\b",
        r"\b(check|status)\b.{0,40}\bapis?\b",
        r"\bapis?\b.{0,40}\b(status|check)\b",
        r"how\s+many\s+(?:are\s+)?(?:still\s+)?(?:there|left)",
    )
    return any(re.search(p, lower) for p in patterns)


def count_apis_from_sheet(text: str = "") -> str:
    """Read sheet CSV and report how many APIs have / still need keys — no LLM."""
    sheet_url = _resolve_sheet_url(text)
    if not sheet_url:
        return (
            "No API sheet saved yet, sir. "
            "Say 'remember my api sheet is [paste the Google Sheets link]', then ask again."
        )

    # Keep registry + workflows in sync when user pastes a URL in the count command
    urls = extract_urls(text)
    if urls:
        set_link("api_sheet", sheet_url)
        set_sheet_url(sheet_url)

    csv_text = fetch_sheet_csv(sheet_url)
    if not csv_text:
        open_google_sheet(sheet_url)
        return (
            "Couldn't read the sheet as CSV just now, sir — I opened it in Chrome. "
            "If it's private, share as 'Anyone with the link can view', then ask again."
        )

    header, data_rows = _parse_sheet_rows(csv_text)
    if not data_rows:
        return "Sheet looks empty, sir — no API rows found."

    # Summary / dashboard tab (Metric, Count) — common on Phantom registry
    if not looks_like_api_table(header):
        metrics = parse_summary_metrics(csv_text)
        if metrics:
            total = (
                metrics.get("total providers")
                or metrics.get("total apis")
                or metrics.get("providers")
                or metrics.get("total")
            )
            # Heuristic remaining / filled keys from common summary labels
            remaining = None
            filled = None
            for key, val in metrics.items():
                if any(w in key for w in ("remaining", "missing", "left", "pending", "todo", "empty")):
                    remaining = val
                if any(w in key for w in ("have key", "with key", "filled", "acquired", "done", "complete", "got")):
                    filled = val
            parts = ["Sheet summary, sir:"]
            if total is not None:
                parts.append(f"{total} APIs total.")
            if filled is not None:
                parts.append(f"{filled} have keys.")
            if remaining is not None:
                parts.append(f"{remaining} still remaining.")
            # Always include a few useful metrics
            extras = []
            for key, val in list(metrics.items())[:8]:
                if key in ("total providers", "total apis", "providers", "total"):
                    continue
                extras.append(f"{key}={val}")
            if extras and (remaining is None and filled is None):
                parts.append("Metrics: " + ", ".join(extras) + ".")
            elif remaining is None and total is not None:
                parts.append("Open the APIs tab for per-row missing keys, or say 'which apis are missing'.")
            return " ".join(parts)

    cols = _find_columns(header)
    name_idx = cols.get("name", 0)
    key_idx = cols.get("key", -1)

    total = 0
    filled = 0
    missing: list[str] = []

    for row in data_rows:
        name = row[name_idx].strip() if name_idx < len(row) else ""
        if not name:
            continue
        # Skip summary-ish labels if we somehow land here
        if name.lower() in ("metric", "count", "summary"):
            continue
        total += 1
        key_val = row[key_idx].strip() if key_idx >= 0 and key_idx < len(row) else ""
        if key_val and len(key_val) > 8:
            filled += 1
        else:
            missing.append(name)

    remaining = len(missing)
    want_names = bool(
        re.search(r"\b(which|missing|list|name|names|what)\b", normalize(text or ""))
    )

    lines = [
        f"Sheet status, sir: {total} APIs total, {filled} have keys, {remaining} still missing.",
    ]
    if remaining == 0:
        lines.append("All listed APIs already have keys.")
    elif want_names or remaining <= 12:
        preview = ", ".join(missing[:12])
        extra = f" (+{remaining - 12} more)" if remaining > 12 else ""
        lines.append(f"Still need keys: {preview}{extra}.")
    else:
        lines.append("Say 'which apis are missing' for the names.")

    return " ".join(lines)
