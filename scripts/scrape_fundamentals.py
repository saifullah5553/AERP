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


def log(msg: str) -> None:
    line = f"{datetime.now(UTC).isoformat(timespec='seconds')}  {msg}"
    print(line, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def targets(regions: list[str]) -> list[tuple[str, str]]:
    """(region, symbol) for every name we could fetch, densest markets first."""
    rows = json.loads(SCREENER.read_text(encoding="utf-8"))
    out: list[tuple[str, str]] = []
    for r in rows:
        region = r.get("region")
        sym = (r.get("symbol") or "").strip().upper()
        if region in regions and sym and sym.replace(".", "").replace("-", "").isalnum():
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


def scrape_table(page, url: str, attempts: int = 2):
    for n in range(attempts):
        df = _scrape_once(page, url)
        if df is not None and len(df) >= MIN_ROWS:
            return df
        if n + 1 < attempts:
            page.wait_for_timeout(1500)
    return None


def _scrape_once(page, url: str):
    """Return a DataFrame of the statement table, or None."""
    import pandas as pd

    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=45000)
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
        # Extract entirely in the page: one round trip instead of a few hundred locator calls,
        # which was most of the per-page cost.
        data = page.evaluate("""() => {
            const tables = [...document.querySelectorAll('table')];
            if (!tables.length) return null;
            const t = tables.reduce((a, b) =>
                b.querySelectorAll('tbody tr').length > a.querySelectorAll('tbody tr').length
                    ? b : a);
            const headers = [...t.querySelectorAll('thead th')]
                .map(h => h.innerText.replace(/\\n/g, ' ').trim()).filter(Boolean);
            const rows = [...t.querySelectorAll('tbody tr')]
                .map(r => [...r.querySelectorAll('td')].map(c => c.innerText.trim()))
                .filter(cells => cells.length);
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
        url = f"https://stockanalysis.com/{prefix}/{sym}/{path}/?p=trailing"
        df = scrape_table(page, url)
        if df is not None and not df.empty:
            df.fillna("", inplace=True)
            df.to_csv(csv_file, index=False, encoding="utf-8")
            written += 1
        time.sleep(page_pause)
    return written


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--regions", default="us,india,australia,psx")
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
