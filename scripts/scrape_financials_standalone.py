#!/usr/bin/env python3
"""Download quarterly-TTM financial statements from stockanalysis.com. Self-contained.

Copy this one file anywhere and run it. No imports from the AERP codebase.

    pip install playwright pandas
    python -m playwright install chromium

    python scrape_financials_standalone.py --regions us,india,australia,gcc
    python scrape_financials_standalone.py --regions us --workers 4      # faster machine
    python scrape_financials_standalone.py --symbols AAPL,MSFT,2222      # targeted refresh

WHERE THE SYMBOLS COME FROM, in order:
    1. --symbols on the command line
    2. --symbols-file, a CSV/TXT with one symbol per line (a `symbol` column if CSV)
    3. data/symbols/<region>.csv or data/universe/<region>.csv beside this script or its parent
    4. frontend/public/data/screener.json (the AERP snapshot)

OUTPUT: data/fundamentals_csv/<region>/<SYMBOL>_<Statement>.csv
        ~20 quarterly TTM columns per statement, each column already a full trailing year.

Resumable: a symbol whose four CSVs already exist is skipped, so stop and restart freely.

---------------------------------------------------------------------------------------------
Everything below was learned the hard way against the live site. Changing any of it will
probably reintroduce a failure that does not look like a failure:

* The statement lives at the EXPLICIT path ("financials/income-statement"). Bare "financials"
  is a landing page carrying a condensed 7-row summary that parses perfectly and is wrong.

* One statement is SPLIT ACROSS SEVERAL TABLES sharing a period grid - a balance sheet arrives
  as assets / liabilities / equity / supplementary. Taking the biggest table silently kept only
  the assets half for 74 of 160 Indian companies: no liabilities, no equity, and nothing
  downstream could tell.

* A row-count check is not enough, so a statement missing its defining lines (Total Liabilities,
  equity, Net Income, Operating Cash Flow) is refused. A truncated statement is worse than a
  missing one because it looks like data.

* stockanalysis spells tickers differently per market: SEC's BRK-B is BRK.B, NSE's BAJAJ-AUTO is
  BAJAJ_AUTO, M&M is M_M. A wrong spelling 404s and reads as "this company has no financials".

* 429 means the SERVER is talking about you, not about that page - so every worker backs off,
  and the pace itself slows permanently. Pushing harder made the run slower: the miss rate went
  from 25% to 70% in one work window before this existed.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOTS = [HERE, HERE.parent]           # look beside this file, then one level up
OUT_DIR = Path("data/fundamentals_csv")
LOG_FILE = Path("data/scrape_financials.log")

# URL prefix per market. Tadawul IS carried, despite the quote path looking nothing like the
# others - GCC was left out of earlier runs on the assumption it was not.
MARKET_PREFIX = {
    "us": "stocks",
    "india": "quote/nse",
    "australia": "quote/asx",
    "gcc": "quote/tadawul",
    "psx": "quote/psx",
}

STATEMENTS = {
    "Income_Statement": "financials/income-statement",
    "Balance_Sheet": "financials/balance-sheet",
    "Cash_Flow": "financials/cash-flow-statement",
    "Ratios": "financials/ratios",
}

# A real statement carries ~30 rows; anything much smaller is a summary or a half-rendered page.
MIN_ROWS = 12

# Each entry is a set of acceptable spellings; every group must match something, or the
# statement is incomplete and is not written.
REQUIRED_LABELS: dict[str, tuple[set[str], ...]] = {
    "Balance_Sheet": (
        {"Total Liabilities"},
        {"Shareholders' Equity", "Total Common Shareholders' Equity", "Total Equity"},
    ),
    "Income_Statement": ({"Net Income"},),
    "Cash_Flow": ({"Operating Cash Flow"},),
}

SKIP_RESOURCES = {"image", "media", "font", "stylesheet"}  # never needed to read a table
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def log(msg: str) -> None:
    line = f"{datetime.now(UTC).isoformat(timespec='seconds')}  {msg}"
    print(line, flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


# ── symbol spelling ──────────────────────────────────────────────────────────────────────
def slug(region: str, symbol: str) -> str:
    """How stockanalysis spells this ticker."""
    sym = symbol.strip().upper()
    if region == "us":
        return sym.replace("-", ".")        # SEC BRK-B -> BRK.B
    if region == "india":
        return sym.replace("-", "_").replace("&", "_")   # BAJAJ-AUTO -> BAJAJ_AUTO, M&M -> M_M
    return sym


def _clean(sym: str) -> str:
    for ch in ".-&_":
        sym = sym.replace(ch, "")
    return sym


def _find(*relatives: str) -> Path | None:
    for root in ROOTS:
        for rel in relatives:
            path = root / rel
            if path.exists():
                return path
    return None


def load_symbols(region: str, symbols_file: str | None) -> list[str]:
    """Symbols for one market, from whichever source is available."""
    if symbols_file:
        path = Path(symbols_file)
        if path.exists():
            text = path.read_text(encoding="utf-8")
            if "," in text.splitlines()[0]:
                return [r["symbol"].strip().upper()
                        for r in csv.DictReader(text.splitlines()) if r.get("symbol")]
            return [ln.strip().upper() for ln in text.splitlines() if ln.strip()]

    listing = _find(f"data/symbols/{region}.csv", f"data/universe/{region}.csv")
    if listing:
        with open(listing, encoding="utf-8") as fh:
            return [r["symbol"].strip().upper()
                    for r in csv.DictReader(fh) if r.get("symbol")]

    snapshot = _find("frontend/public/data/screener.json")
    if snapshot:
        rows = json.loads(snapshot.read_text(encoding="utf-8"))
        return [str(r["symbol"]).strip().upper() for r in rows
                if r.get("region") == region and r.get("symbol")]

    return []


# ── rate limiting ────────────────────────────────────────────────────────────────────────
_LOCK = threading.Lock()
_cooldown_until = 0.0
_cooldown = 120.0
_extra_delay = 0.0
MAX_COOLDOWN = 900.0
MAX_EXTRA_DELAY = 6.0


def _throttled() -> None:
    """Back every worker off, harder each time, and slow the steady-state pace."""
    global _cooldown_until, _cooldown, _extra_delay
    with _LOCK:
        if time.time() < _cooldown_until:
            return                       # already backing off; don't compound
        wait, _cooldown_until = _cooldown, time.time() + _cooldown
        _cooldown = min(_cooldown * 2, MAX_COOLDOWN)
        _extra_delay = min(_extra_delay + 0.5, MAX_EXTRA_DELAY)
        slower = _extra_delay
    log(f"  rate limited (429) - backing off {wait:.0f}s, pacing +{slower:.1f}s/page")


def _cleared() -> None:
    """Decay far slower than it grows; recovering fast walks straight into the next 429."""
    global _cooldown, _extra_delay
    with _LOCK:
        _cooldown = 120.0
        _extra_delay = max(0.0, _extra_delay - 0.02)


def _wait_out_cooldown() -> None:
    while True:
        with _LOCK:
            remaining = _cooldown_until - time.time()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 5.0))


def _pace() -> float:
    with _LOCK:
        return _extra_delay


# ── scraping ─────────────────────────────────────────────────────────────────────────────
# Concatenate every table of the same width, deduped by row label: that is what reassembles a
# split statement. Read headers from the widest table.
_EXTRACT_JS = """() => {
    const tables = [...document.querySelectorAll('table')];
    if (!tables.length) return null;
    const rowsOf = t => t.querySelectorAll('tbody tr').length;
    const anchor = tables.reduce((a, b) => rowsOf(b) > rowsOf(a) ? b : a);
    const headers = [...anchor.querySelectorAll('thead th')]
        .map(h => h.innerText.replace(/\\n/g, ' ').trim()).filter(Boolean);
    const width = anchor.querySelectorAll('thead th').length;
    const rows = [], seen = new Set();
    for (const t of tables) {
        if (t.querySelectorAll('thead th').length !== width) continue;
        for (const r of t.querySelectorAll('tbody tr')) {
            const cells = [...r.querySelectorAll('td')].map(c => c.innerText.trim());
            if (!cells.length || seen.has(cells[0])) continue;
            seen.add(cells[0]);
            rows.push(cells);
        }
    }
    return {headers, rows};
}"""


def _complete(df, statement: str) -> bool:
    groups = REQUIRED_LABELS.get(statement)
    if not groups:
        return True
    labels = {str(x).strip() for x in df.iloc[:, 0]}
    return all(labels & group for group in groups)


def _scrape_once(page, url: str):
    import pandas as pd

    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=45000)
        if resp and resp.status == 429:
            _throttled()
            return None
        if not resp or resp.status >= 400:
            return None

        # Wait for a table big enough to BE a statement. Waiting for "a table" returns
        # instantly on the static summary.
        page.wait_for_function(
            "n => [...document.querySelectorAll('table')]"
            ".some(t => t.querySelectorAll('tbody tr').length >= n)",
            arg=MIN_ROWS, timeout=20000,
        )
        data = page.evaluate(_EXTRACT_JS)
        if not data or not data["headers"] or not data["rows"]:
            return None

        headers, rows = data["headers"], []
        for cells in data["rows"]:
            if len(cells) == len(headers) * 2:      # some rows repeat the label column
                cells = cells[: len(headers)]
            elif len(cells) != len(headers):
                cells = cells[: len(headers)] + [""] * max(0, len(headers) - len(cells))
            rows.append(cells)
        return pd.DataFrame(rows, columns=headers) if rows else None
    except Exception:  # noqa: BLE001 - one bad page must never stop a multi-day run
        return None


def scrape_table(page, url: str, statement: str | None = None, attempts: int = 3):
    for n in range(attempts):
        _wait_out_cooldown()
        df = _scrape_once(page, url)
        if df is not None and len(df) >= MIN_ROWS and (
            statement is None or _complete(df, statement)
        ):
            _cleared()
            return df
        if n + 1 < attempts:
            page.wait_for_timeout(1500)
    return None


def already_done(region: str, sym: str) -> bool:
    d = OUT_DIR / region
    return all((d / f"{sym}_{name}.csv").exists()
               and (d / f"{sym}_{name}.csv").stat().st_size > 10
               for name in STATEMENTS)


def scrape_symbol(page, region: str, sym: str, page_pause: float) -> int:
    d = OUT_DIR / region
    d.mkdir(parents=True, exist_ok=True)
    written = 0
    for name, path in STATEMENTS.items():
        csv_file = d / f"{sym}_{name}.csv"
        if csv_file.exists() and csv_file.stat().st_size > 10:
            continue
        # ?p=trailing gives quarterly-spaced TTM columns - each already a full trailing year.
        url = (f"https://stockanalysis.com/{MARKET_PREFIX[region]}/"
               f"{slug(region, sym)}/{path}/?p=trailing")
        df = scrape_table(page, url, statement=name)
        if df is not None and not df.empty:
            df.fillna("", inplace=True)
            df.to_csv(csv_file, index=False, encoding="utf-8")
            written += 1
        time.sleep(page_pause + _pace())
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--regions", default="us,india,australia,gcc",
                    help="comma list: us,india,australia,gcc,psx")
    ap.add_argument("--symbols", default=None, help="comma list; forces a refresh of these")
    ap.add_argument("--symbols-file", default=None, help="CSV/TXT, one symbol per line")
    ap.add_argument("--workers", type=int, default=2,
                    help="parallel browsers. 3+ got us rate limited; raise carefully")
    ap.add_argument("--page-pause", type=float, default=1.0, help="seconds between pages")
    ap.add_argument("--work", type=float, default=90.0, help="minutes of scraping per cycle")
    ap.add_argument("--rest", type=float, default=30.0, help="minutes of rest between cycles")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    regions = [r.strip() for r in args.regions.split(",") if r.strip() in MARKET_PREFIX]
    todo: list[tuple[str, str]] = []
    for region in regions:
        if args.symbols:
            wanted = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
            for sym in wanted:
                for name in STATEMENTS:      # a forced refresh must clear the skip
                    (OUT_DIR / region / f"{sym}_{name}.csv").unlink(missing_ok=True)
            todo += [(region, s) for s in wanted]
        else:
            syms = load_symbols(region, args.symbols_file)
            if not syms:
                log(f"{region}: no symbol list found - skipping")
                continue
            todo += [(region, s) for s in syms
                     if _clean(s).isalnum() and not already_done(region, s)]

    if args.limit:
        todo = todo[: args.limit]
    if not todo:
        log("nothing to do - everything already downloaded")
        return 0
    log(f"=== start: {len(todo)} symbols across {regions} "
        f"({args.workers} workers, work {args.work}m / rest {args.rest}m) ===")

    state = {"idx": 0, "done": 0, "failed": 0}
    lock = threading.Lock()

    def worker(cycle_end: float) -> None:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            ctx = browser.new_context(viewport={"width": 1280, "height": 850}, user_agent=UA)
            ctx.route("**/*", lambda route: route.abort()
                      if route.request.resource_type in SKIP_RESOURCES else route.continue_())
            page = ctx.new_page()
            while True:
                with lock:
                    if state["idx"] >= len(todo) or time.time() >= cycle_end:
                        break
                    i = state["idx"]
                    state["idx"] += 1
                region, sym = todo[i]
                try:
                    key = "done" if scrape_symbol(page, region, sym, args.page_pause) else "failed"
                except Exception as exc:  # noqa: BLE001
                    key = "failed"
                    log(f"  {region}/{sym}: {type(exc).__name__}")
                with lock:
                    state[key] += 1
                    seen = state["idx"]
                if seen % 50 == 0:
                    log(f"  progress {seen}/{len(todo)} | saved {state['done']} "
                        f"| no-data {state['failed']}")
            browser.close()

    while state["idx"] < len(todo):
        cycle_end = time.time() + args.work * 60
        threads = [threading.Thread(target=worker, args=(cycle_end,), daemon=True)
                   for _ in range(max(1, args.workers))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        if state["idx"] < len(todo):
            log(f"--- cycle done at {state['idx']}/{len(todo)} (saved {state['done']}) "
                f"- resting {args.rest}m ---")
            time.sleep(args.rest * 60)

    log(f"=== COMPLETE: {state['done']} symbols saved, {state['failed']} without usable data ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
