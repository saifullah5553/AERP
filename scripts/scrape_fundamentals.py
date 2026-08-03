"""Download quarterly-TTM financials for the whole universe from stockanalysis.com.

Why this exists: yfinance gives 2-4 sparse TTM points per name and freezes under load, while
stockanalysis serves ~20 quarterly TTM columns (5 years) in the same CSV shape PSX already
uses. Owning that data locally removes the rate-limit dependency entirely and makes every
market's quality score comparable, instead of PSX-from-stockanalysis vs everything-else-from-
yfinance.

The full statement tables are rendered client-side (the static HTML carries only a condensed
7-row summary), so this drives a headless browser. That is slow, which is the whole reason for
the duty cycle:

    work WORK_MINUTES, then sleep REST_MINUTES, repeat

Being a considerate scraper is not politeness theatre here - it is what keeps us from being
blocked halfway through a multi-day run. There is also a per-page pause inside each work
window.

Fully resumable: a symbol whose CSVs already exist is skipped, so the job can be stopped and
restarted freely, and a later run costs nothing for work already done.

    python scripts/scrape_fundamentals.py                  # everything, default cadence
    python scripts/scrape_fundamentals.py --regions us     # one market
    python scripts/scrape_fundamentals.py --work 120 --rest 30
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCREENER = REPO / "frontend" / "public" / "data" / "screener.json"
OUT_DIR = Path(os.environ.get("AERP_FUND_CSV_DIR", REPO / "data" / "fundamentals_csv"))
LOG = REPO / "data" / "scrape_fundamentals.log"

# Never needed for reading a table, and they are most of the bytes on these pages.
_SKIP_RESOURCES = {"image", "media", "font", "stylesheet"}

# stockanalysis URL prefix per market. PSX already has its own folder from the earlier scrape,
# but it is included so a single command can top up everything.
MARKET_PREFIX = {
    "us": "stocks",
    "india": "quote/nse",
    "australia": "quote/asx",
    # Tadawul IS carried, despite the quote path resembling none of the others. GCC was left
    # out of earlier runs on the assumption it was not - verified against Aramco (2222).
    "gcc": "quote/tadawul",
    "psx": "quote/psx",
}
STATEMENTS = {
    # NOT bare "financials" - that landing page carries only a condensed 7-row summary
    # (Revenue/Gross Profit/Operating Income/Net Income/EPS). The full ~48-row statement,
    # matching the PSX CSV shape, lives at the explicit income-statement path.
    "Income_Statement": "financials/income-statement",
    "Balance_Sheet": "financials/balance-sheet",
    "Cash_Flow": "financials/cash-flow-statement",
    # Ratios carries PE/PB/ROE/debt-to-equity/current-ratio per TTM quarter - the screener
    # metrics we currently recompute or leave blank for non-PSX names.
    "Ratios": "financials/ratios",
}


# stockanalysis spells multi-class and ampersand tickers differently from the exchange feeds we
# build the universe from, and differently per market. Getting this wrong is silent: the URL
# 404s, the symbol is logged as "no data", and it looks like a company without financials.
#   US     SEC gives BRK-B, stockanalysis wants BRK.B      (427 of our US symbols carry a dash)
#   India  NSE gives BAJAJ-AUTO, stockanalysis wants BAJAJ_AUTO; M&M becomes M_M
#
# data/symbols/<region>.csv is the registry that settles this for the whole platform (built by
# app.ingestion.symbols, which also derives the yfinance spelling used for prices). Reading it
# here keeps one answer per company rather than a copy of the rules that can drift; the inline
# rules below are only the fallback for a market with no registry file yet.
SYMBOLS_DIR = REPO / "data" / "symbols"
_SLUGS: dict[str, dict[str, str]] = {}


def _registry(region: str) -> dict[str, str]:
    if region not in _SLUGS:
        table: dict[str, str] = {}
        path = SYMBOLS_DIR / f"{region}.csv"
        if path.exists():
            with open(path, encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    sym = (row.get("symbol") or "").strip().upper()
                    sa = (row.get("stockanalysis") or "").strip()
                    if sym and sa:
                        table[sym] = sa
        _SLUGS[region] = table
    return _SLUGS[region]


def slug(region: str, symbol: str) -> str:
    known = _registry(region).get(symbol.upper())
    if known:
        return known
    if region == "us":
        return symbol.replace("-", ".")
    if region == "india":
        return symbol.replace("-", "_").replace("&", "_")
    return symbol


def log(msg: str) -> None:
    line = f"{datetime.now(UTC).isoformat(timespec='seconds')}  {msg}"
    print(line, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def _clean(sym: str) -> str:
    for ch in ".-&_":
        sym = sym.replace(ch, "")
    return sym


def targets(regions: list[str]) -> list[tuple[str, str]]:
    """(region, symbol) for every name we could fetch, densest markets first."""
    rows = json.loads(SCREENER.read_text(encoding="utf-8"))
    out: list[tuple[str, str]] = []
    for r in rows:
        region = r.get("region")
        sym = (r.get("symbol") or "").strip().upper()
        # & and _ are legitimate in Indian tickers (M&M, ARE_M). Excluding them dropped
        # those companies from the run entirely rather than failing visibly.
        if region in regions and sym and _clean(sym).isalnum():
            out.append((region, sym))
    # Highest-quality names first so the most useful data lands earliest, in case the run is
    # interrupted or blocked partway through.
    order = {s: i for i, s in enumerate(
        (r.get("symbol") or "").upper() for r in sorted(
            rows, key=lambda x: (x.get("quality_score") is not None,
                                 x.get("quality_score") or 0), reverse=True)
    )}
    out.sort(key=lambda t: order.get(t[1], 10**9))
    return out


# A real statement carries ~30 rows. Anything much smaller is the condensed summary or a
# half-rendered page - writing it would poison the dataset far more quietly than failing does,
# and a miss is free to retry because the run is resumable.
MIN_ROWS = 12


# Shared cooldown. A 429 is not a property of one page - the server is telling every worker to
# back off, so one worker seeing it must pause all of them. Without this the run keeps hammering
# through the throttle and the miss rate climbs (observed: 25% -> 70% over one work window),
# which quietly costs far more time than waiting would.
_COOLDOWN_UNTIL = 0.0
_COOLDOWN_LOCK = threading.Lock()
COOLDOWN_SECONDS = 120.0
MAX_COOLDOWN_SECONDS = 900.0
_cooldown = COOLDOWN_SECONDS
_extra_delay = 0.0
MAX_EXTRA_DELAY = 6.0


def _throttled() -> None:
    """Back every worker off, and back off harder each time it keeps happening.

    A fixed pause guesses at a rate the server never told us. Doubling until the 429s stop, and
    resetting on the first success, lets the run settle at whatever rate is actually tolerated -
    which matters because a throttled fetch costs three attempts and yields nothing, so pushing
    harder makes the run slower, not faster.
    """
    global _COOLDOWN_UNTIL, _cooldown, _extra_delay
    with _COOLDOWN_LOCK:
        first = time.time() >= _COOLDOWN_UNTIL
        if not first:
            return  # already backing off; don't compound within one window
        wait = _cooldown
        _COOLDOWN_UNTIL = time.time() + wait
        _cooldown = min(_cooldown * 2, MAX_COOLDOWN_SECONDS)
        _extra_delay = min(_extra_delay + 0.5, MAX_EXTRA_DELAY)
        slower = _extra_delay
    log(f"  rate limited (429) - backing off {wait:.0f}s, pacing +{slower:.1f}s/page")


def _throttle_cleared() -> None:
    """A clean fetch means the current pace is tolerated; ease back off slowly."""
    global _cooldown, _extra_delay
    with _COOLDOWN_LOCK:
        _cooldown = COOLDOWN_SECONDS
        # Decay far slower than it grows. Recovering quickly just walks back into the next 429,
        # which is the oscillation this is here to stop.
        _extra_delay = max(0.0, _extra_delay - 0.02)


def pace() -> float:
    """Extra seconds to wait between pages, learned from the 429s we have seen.

    Pausing on a 429 alone is not enough: once the pause ends the run returns to exactly the
    pace that caused it, so it oscillates between bursting and being throttled. Slowing the
    steady-state rate is what actually settles it.
    """
    with _COOLDOWN_LOCK:
        return _extra_delay


def _wait_out_cooldown() -> None:
    while True:
        with _COOLDOWN_LOCK:
            remaining = _COOLDOWN_UNTIL - time.time()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 5.0))


# Row counts alone do not prove a statement is whole. These pages split a statement across
# several tables, and a half-captured balance sheet - assets present, liabilities and equity
# missing - still clears MIN_ROWS while quietly removing debt and equity from the quality gate.
# Each entry is a list of alternatives; every group must match something.
REQUIRED_LABELS: dict[str, tuple[set[str], ...]] = {
    "Balance_Sheet": (
        {"Total Liabilities"},
        {"Shareholders' Equity", "Total Common Shareholders' Equity", "Total Equity"},
    ),
    "Income_Statement": ({"Net Income"},),
    "Cash_Flow": ({"Operating Cash Flow"},),
}


def _complete(df, statement: str) -> bool:
    groups = REQUIRED_LABELS.get(statement)
    if not groups:
        return True
    labels = {str(x).strip() for x in df.iloc[:, 0]}
    return all(labels & group for group in groups)


def scrape_table(page, url: str, attempts: int = 3, statement: str | None = None):
    for n in range(attempts):
        _wait_out_cooldown()
        df = _scrape_once(page, url)
        if df is not None and len(df) >= MIN_ROWS and (
            statement is None or _complete(df, statement)
        ):
            _throttle_cleared()
            return df
        if n + 1 < attempts:
            page.wait_for_timeout(1500)
    return None


def _scrape_once(page, url: str):
    """Return a DataFrame of the statement table, or None."""
    import pandas as pd

    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=45000)
        if resp and resp.status == 429:
            _throttled()
            return None
        if not resp or resp.status >= 400:
            return None
        # These pages carry several tables (a condensed summary, segment splits, valuation
        # teasers) and the statement is neither reliably first nor tagged, so we take the one
        # with the most rows. Wait for a table that is actually big enough to BE a statement:
        # waiting only for "a table" returns instantly on the static summary, which is how the
        # condensed version got saved in the first place.
        page.wait_for_function(
            "n => [...document.querySelectorAll('table')]"
            ".some(t => t.querySelectorAll('tbody tr').length >= n)",
            arg=MIN_ROWS, timeout=20000,
        )
        # ...then wait for the row count to STOP growing. Waiting only for "enough rows" grabs
        # the table mid-render: it captured Indian balance sheets that stopped at Total Assets,
        # with the whole liabilities-and-equity half missing, and they passed the row check
        # because a half-rendered table still clears MIN_ROWS. A truncated statement is the
        # worst outcome here - it looks like real data and silently removes debt and equity
        # from the quality gate.
        prev = -1
        for _ in range(12):
            count = page.evaluate(
                "() => Math.max(0, ...[...document.querySelectorAll('table')]"
                ".map(t => t.querySelectorAll('tbody tr').length))"
            )
            if count == prev:
                break
            prev = count
            page.wait_for_timeout(400)
        # Extract entirely in the page: one round trip instead of a few hundred locator calls,
        # which was most of the per-page cost.
        data = page.evaluate("""() => {
            const tables = [...document.querySelectorAll('table')];
            if (!tables.length) return null;
            const rowsOf = t => t.querySelectorAll('tbody tr').length;
            const anchor = tables.reduce((a, b) => rowsOf(b) > rowsOf(a) ? b : a);
            const headers = [...anchor.querySelectorAll('thead th')]
                .map(h => h.innerText.replace(/\\n/g, ' ').trim()).filter(Boolean);
            // A statement is split across several tables sharing one period grid - a balance
            // sheet arrives as assets / liabilities / equity / supplementary. Same column
            // count means same grid, so take them all; anything else on the page (condensed
            // summaries, valuation teasers) has a different width and is left out.
            const width = anchor.querySelectorAll('thead th').length;
            const rows = [];
            const seen = new Set();
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
        }""")
        if not data or not data["headers"] or not data["rows"]:
            return None
        headers, rows = data["headers"], []
        for cells in data["rows"]:
            if len(cells) == len(headers) * 2:      # some rows duplicate the label column
                cells = cells[: len(headers)]
            elif len(cells) != len(headers):
                cells = cells[: len(headers)] + [""] * max(0, len(headers) - len(cells))
            rows.append(cells)
        return pd.DataFrame(rows, columns=headers) if rows else None
    except Exception:  # noqa: BLE001 - one bad page must never stop a multi-day run
        return None


def already_done(region: str, sym: str) -> bool:
    d = OUT_DIR / region
    return all((d / f"{sym}_{name}.csv").exists()
               and (d / f"{sym}_{name}.csv").stat().st_size > 10
               for name in STATEMENTS)


def scrape_symbol(page, region: str, sym: str, page_pause: float) -> int:
    prefix = MARKET_PREFIX[region]
    d = OUT_DIR / region
    d.mkdir(parents=True, exist_ok=True)
    written = 0
    for name, path in STATEMENTS.items():
        csv_file = d / f"{sym}_{name}.csv"
        if csv_file.exists() and csv_file.stat().st_size > 10:
            continue
        # ?p=trailing gives the quarterly-spaced TTM columns - each already a full trailing
        # year, which is exactly what the quality engine and its trend need.
        url = f"https://stockanalysis.com/{prefix}/{slug(region, sym)}/{path}/?p=trailing"
        df = scrape_table(page, url, statement=name)
        if df is not None and not df.empty:
            df.fillna("", inplace=True)
            df.to_csv(csv_file, index=False, encoding="utf-8")
            written += 1
        time.sleep(page_pause + pace())
    return written


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--regions", default="us,india,australia,gcc,psx")
    ap.add_argument("--work", type=float, default=120.0, help="minutes of scraping per cycle")
    ap.add_argument("--rest", type=float, default=30.0, help="minutes of rest between cycles")
    ap.add_argument("--page-pause", type=float, default=0.8, help="seconds between page loads")
    ap.add_argument("--workers", type=int, default=4,
                    help="parallel browsers; each is one more concurrent page load")
    ap.add_argument("--symbols", default=None,
                    help="comma list to refresh; re-fetches them even if already downloaded")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    regions = [r.strip() for r in args.regions.split(",") if r.strip() in MARKET_PREFIX]
    if args.symbols:
        # A targeted refresh: these names just reported, so their existing CSVs are stale by
        # definition. Clear them first, otherwise the per-file skip would make this a no-op.
        wanted = {s.strip().upper() for s in args.symbols.split(",") if s.strip()}
        todo = [t for t in targets(regions) if t[1] in wanted]
        for region, sym in todo:
            for name in STATEMENTS:
                (OUT_DIR / region / f"{sym}_{name}.csv").unlink(missing_ok=True)
    else:
        todo = [t for t in targets(regions) if not already_done(*t)]
    if args.limit:
        todo = todo[: args.limit]
    log(f"=== start: {len(todo)} symbols to fetch across {regions} "
        f"(work {args.work}m / rest {args.rest}m, {args.workers} workers) ===")
    if not todo:
        log("nothing to do - everything already downloaded")
        return 0

    state = {"idx": 0, "done": 0, "failed": 0}
    lock = threading.Lock()

    def worker(cycle_end: float) -> None:
        """One browser, pulling symbols off the shared queue until the window closes."""
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            ctx = browser.new_context(
                viewport={"width": 1280, "height": 850},
                user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
            )
            # We only ever read a table. Images, fonts, stylesheets and media are pure download
            # cost on pages this heavy, and they dominated the per-page time.
            ctx.route(
                "**/*",
                lambda route: route.abort()
                if route.request.resource_type in _SKIP_RESOURCES
                else route.continue_(),
            )
            page = ctx.new_page()
            while True:
                with lock:
                    if state["idx"] >= len(todo) or time.time() >= cycle_end:
                        break
                    i = state["idx"]
                    state["idx"] += 1
                region, sym = todo[i]
                try:
                    n = scrape_symbol(page, region, sym, args.page_pause)
                    key = "done" if n else "failed"
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

        idx, done = state["idx"], state["done"]
        if idx < len(todo):
            log(f"--- cycle done at {idx}/{len(todo)} (saved {done}) - resting "
                f"{args.rest}m so stockanalysis doesn't throttle us ---")
            time.sleep(args.rest * 60)

    log(f"=== COMPLETE: {state['done']} symbols saved, "
        f"{state['failed']} without usable data ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
