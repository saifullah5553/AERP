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
import time
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCREENER = REPO / "frontend" / "public" / "data" / "screener.json"
OUT_DIR = Path(os.environ.get("AERP_FUND_CSV_DIR", REPO / "data" / "fundamentals_csv"))
LOG = REPO / "data" / "scrape_fundamentals.log"

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


def scrape_table(page, url: str):
    """Return a DataFrame of the statement table, or None."""
    import pandas as pd

    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=45000)
        if not resp or resp.status >= 400:
            return None
        page.wait_for_selector("table", timeout=12000)
        # These pages carry several tables (a condensed summary, segment splits, valuation
        # teasers) and the full statement is not reliably first or tagged. Taking the one with
        # the most rows picks the real statement on every page type and survives reshuffles;
        # the poll gives the client-rendered table time to replace the static summary.
        tables = page.locator("table")
        table, best = None, 0
        for _ in range(8):
            for i in range(tables.count()):
                n = tables.nth(i).locator("tbody tr").count()
                if n > best:
                    table, best = tables.nth(i), n
            if best >= 15:
                break
            page.wait_for_timeout(700)
        if table is None:
            return None
        headers = [h.replace("\n", " ").strip()
                   for h in table.locator("thead th").all_inner_texts() if h.strip()]
        if not headers:
            return None
        rows = []
        for row in table.locator("tbody tr").all():
            cells = [c.strip() for c in row.locator("td").all_inner_texts()]
            if not cells:
                continue
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
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    regions = [r.strip() for r in args.regions.split(",") if r.strip() in MARKET_PREFIX]
    todo = [t for t in targets(regions) if not already_done(*t)]
    if args.limit:
        todo = todo[: args.limit]
    log(f"=== start: {len(todo)} symbols to fetch across {regions} "
        f"(work {args.work}m / rest {args.rest}m) ===")
    if not todo:
        log("nothing to do - everything already downloaded")
        return 0

    done = failed = 0
    idx = 0
    while idx < len(todo):
        cycle_end = time.time() + args.work * 60
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
            page = ctx.new_page()
            while idx < len(todo) and time.time() < cycle_end:
                region, sym = todo[idx]
                idx += 1
                try:
                    n = scrape_symbol(page, region, sym, args.page_pause)
                    if n:
                        done += 1
                    else:
                        failed += 1
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    log(f"  {region}/{sym}: {type(exc).__name__}")
                if idx % 25 == 0:
                    log(f"  progress {idx}/{len(todo)} | saved {done} | no-data {failed}")
            browser.close()

        if idx < len(todo):
            log(f"--- cycle done at {idx}/{len(todo)} (saved {done}) - resting "
                f"{args.rest}m so stockanalysis doesn't throttle us ---")
            time.sleep(args.rest * 60)

    log(f"=== COMPLETE: {done} symbols saved, {failed} without usable data ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
