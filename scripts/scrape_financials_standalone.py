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
    5. HARVESTED from the site's own list page, and cached to data/universe/<region>.csv so it
       happens once. This is what lets the script run on a machine holding nothing but itself.

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
import traceback
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOTS = [HERE, HERE.parent]           # look beside this file, then one level up

# Everything is written NEXT TO THIS SCRIPT, not into the current working directory.
# Relative paths meant the output landed wherever you happened to launch from - and worse,
# launching from the Windows user profile crashed outright with "Access is denied: 'data'",
# because Controlled Folder Access refuses folder creation there. --out overrides.
BASE_DIR = HERE
OUT_DIR = BASE_DIR / "data" / "fundamentals_csv"
LOG_FILE = BASE_DIR / "data" / "scrape_financials.log"
UNIVERSE_DIR = BASE_DIR / "data" / "universe"


def set_base_dir(path: Path) -> None:
    """Point every output at `path`. Called once, before anything is written."""
    global BASE_DIR, OUT_DIR, LOG_FILE, UNIVERSE_DIR
    BASE_DIR = path.expanduser().resolve()
    OUT_DIR = BASE_DIR / "data" / "fundamentals_csv"
    LOG_FILE = BASE_DIR / "data" / "scrape_financials.log"
    UNIVERSE_DIR = BASE_DIR / "data" / "universe"


def check_writable() -> None:
    """Fail immediately, and readably, if we cannot write where we are about to write.

    Discovering this mid-run - after harvesting 5,601 symbols - wastes the whole run and
    surfaces as a bare WinError 5 deep inside pathlib.
    """
    try:
        UNIVERSE_DIR.mkdir(parents=True, exist_ok=True)
        probe = UNIVERSE_DIR / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        print(
            f"\nCannot write to {BASE_DIR}\n"
            f"  {type(exc).__name__}: {exc}\n\n"
            "Windows blocks folder creation in some locations - Controlled Folder Access\n"
            "protects the user profile. Move the script somewhere writable, or pass:\n"
            "    --out D:\\financials\n",
            flush=True,
        )
        raise SystemExit(2) from exc

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


# Where each market's full listing lives. Harvesting these is what makes the script
# self-sufficient: without it there is no symbol list on a fresh machine and the run silently
# does nothing, which is exactly how the first version failed.
LIST_URL = {
    "us": "https://stockanalysis.com/stocks/",
    "india": "https://stockanalysis.com/list/nse-india/",
    "australia": "https://stockanalysis.com/list/australian-securities-exchange/",
    "gcc": "https://stockanalysis.com/list/saudi-stock-exchange/",
    "psx": "https://stockanalysis.com/list/pakistan-stock-exchange/",
}
_LIST_JS = """() => {
    const tables = [...document.querySelectorAll('table')];
    if (!tables.length) return [];
    const t = tables.reduce((a, b) =>
        b.querySelectorAll('tbody tr').length > a.querySelectorAll('tbody tr').length ? b : a);
    const heads = [...t.querySelectorAll('thead th')].map(h => h.innerText.trim().toLowerCase());
    let iSym = heads.indexOf('symbol');
    if (iSym < 0) iSym = heads.length > 1 ? 1 : 0;   // some lists lead with a row number
    return [...t.querySelectorAll('tbody tr')]
        .map(r => {
            const tds = [...r.querySelectorAll('td')].map(c => c.innerText.trim());
            return iSym < tds.length ? tds[iSym] : '';
        })
        .filter(Boolean);
}"""


def harvest_symbols(page, region: str) -> list[str]:
    """Every listed ticker for a market, straight off the site's own list page.

    The lists page 500 at a time behind a "Next" link (a link, not a button - matching it as a
    button silently stops at the first 500). After clicking we wait for the first row to
    actually change rather than for a fixed interval: a fixed wait truncated this at 1,000 of
    3,020 the moment a page rendered slowly, and truncation looks exactly like "that is the
    whole market".
    """
    url = LIST_URL.get(region)
    if not url:
        return []
    found: list[str] = []
    seen: set[str] = set()
    stalls = 0
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_function(
            "() => [...document.querySelectorAll('table')]"
            ".some(t => t.querySelectorAll('tbody tr').length > 10)",
            timeout=25000,
        )
        # The page states its own size ("383 Stocks"). Trust it as the bound: when a market
        # fits on one page there is still a "Next" control, and following it walked off the
        # Saudi list into a US table - 983 "Saudi" symbols, 600 of them XOM, JNJ, ASML. A
        # symbol list that is quietly 60% another market is worse than no list at all.
        declared = page.evaluate(
            r"""() => {
                const m = document.body.innerText.match(/([0-9][0-9,]*)\s+[Ss]tocks?\b/);
                return m ? parseInt(m[1].replace(/,/g, ''), 10) : null;
            }"""
        )
        if declared:
            log(f"  {region}: listing declares {declared} stocks")

        for _ in range(60):
            rows = page.evaluate(_LIST_JS)
            for sym in rows:
                s = sym.strip().upper()
                if s and s not in seen:
                    seen.add(s)
                    found.append(s)
            if declared and len(found) >= declared:
                break
            nxt = page.locator("button:has-text('Next'), a:has-text('Next')")
            if nxt.count() == 0 or not nxt.first.is_enabled():
                break
            head = rows[0] if rows else ""
            nxt.first.click()
            try:
                # Compare the SYMBOL, resolved by header exactly as the extractor does. An
                # earlier version compared against every cell in the row, so a leading "No."
                # column made it true instantly: we then re-read the stale page, saw only
                # symbols we already had, and stopped early - 2,020 of 3,020 Indian names,
                # reported as success.
                page.wait_for_function(
                    """h => {
                        const ts = [...document.querySelectorAll('table')];
                        if (!ts.length) return false;
                        const t = ts.reduce((a, b) =>
                            b.querySelectorAll('tbody tr').length >
                            a.querySelectorAll('tbody tr').length ? b : a);
                        const heads = [...t.querySelectorAll('thead th')]
                            .map(x => x.innerText.trim().toLowerCase());
                        let i = heads.indexOf('symbol');
                        if (i < 0) i = heads.length > 1 ? 1 : 0;
                        const first = t.querySelector('tbody tr');
                        if (!first) return false;
                        const tds = [...first.querySelectorAll('td')];
                        return i < tds.length && tds[i].innerText.trim() !== h;
                    }""",
                    arg=head, timeout=20000,
                )
            except Exception:  # noqa: BLE001
                # A slow page is not the end of the list. Giving up on the first timeout
                # stopped the US harvest at 3,509 of 5,601 and called it done.
                if declared and len(found) < declared and stalls < 3:
                    stalls += 1
                    page.wait_for_timeout(3000)
                    continue
                break
    except Exception as exc:  # noqa: BLE001
        log(f"  {region}: could not harvest the listing ({type(exc).__name__})")

    if declared and len(found) > declared:
        log(f"  {region}: trimming {len(found)} harvested to the declared {declared}")
        found = found[:declared]
    return found


def load_symbols(page, region: str, symbols_file: str | None) -> list[str]:
    """Symbols for one market. Cached after the first harvest so it happens once."""
    if symbols_file:
        path = Path(symbols_file)
        if path.exists():
            lines = path.read_text(encoding="utf-8").splitlines()
            if lines and "," in lines[0]:
                return [r["symbol"].strip().upper()
                        for r in csv.DictReader(lines) if r.get("symbol")]
            return [ln.strip().upper() for ln in lines if ln.strip()]

    cached = UNIVERSE_DIR / f"{region}.csv"
    for listing in (cached, _find(f"data/symbols/{region}.csv") or cached):
        if listing.exists():
            with open(listing, encoding="utf-8") as fh:
                syms = [r["symbol"].strip().upper()
                        for r in csv.DictReader(fh) if r.get("symbol")]
            if syms:
                return syms

    snapshot = _find("frontend/public/data/screener.json")
    if snapshot:
        rows = json.loads(snapshot.read_text(encoding="utf-8"))
        syms = [str(r["symbol"]).strip().upper() for r in rows
                if r.get("region") == region and r.get("symbol")]
        if syms:
            return syms

    log(f"  {region}: no local list - harvesting from {LIST_URL.get(region, '?')}")
    syms = harvest_symbols(page, region)
    if syms:
        UNIVERSE_DIR.mkdir(parents=True, exist_ok=True)
        with open(cached, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["symbol"])
            w.writerows([[s] for s in syms])
        log(f"  {region}: harvested {len(syms)} symbols -> {cached}")
    return syms


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


def open_browser(p, headless: bool, slow_mo: int, block_assets: bool | None = None):
    """A real browser window by default.

    Headless Chromium is detectable and, more practically, gives you nothing to look at when a
    run misbehaves - you cannot see a consent wall, a challenge page, or a layout change. A
    visible window with a small delay between actions is slower per page but far easier to
    trust, and it is what a person driving the site would produce.

    Stylesheets, images and fonts are blocked ONLY when headless. They are most of the bytes
    and none of the data, so dropping them is free when nobody is looking - but in a visible
    window it renders the site unstyled and broken, which is indistinguishable from the page
    failing to load. If you are watching, you should see what a person would see.
    """
    if block_assets is None:
        block_assets = headless
    browser = p.chromium.launch(
        headless=headless,
        slow_mo=slow_mo,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox",
              "--start-maximized"],
    )
    ctx = browser.new_context(
        viewport={"width": 1440, "height": 900},
        user_agent=UA,
        locale="en-US",
    )
    if block_assets:
        ctx.route("**/*", lambda route: route.abort()
                  if route.request.resource_type in SKIP_RESOURCES else route.continue_())
    return browser, ctx, ctx.new_page()


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
    ap.add_argument("--workers", type=int, default=1,
                    help="parallel browsers. 3+ got us rate limited; each opens its own window")
    ap.add_argument("--headless", action="store_true",
                    help="hide the browser. Default is a real visible window")
    ap.add_argument("--slow-mo", type=int, default=120,
                    help="ms Playwright waits between actions, so it moves at human pace")
    ap.add_argument("--page-pause", type=float, default=1.0, help="seconds between pages")
    ap.add_argument("--work", type=float, default=90.0, help="minutes of scraping per cycle")
    ap.add_argument("--rest", type=float, default=30.0, help="minutes of rest between cycles")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", default=None,
                    help="where to write data/ (default: next to this script)")
    args = ap.parse_args()

    if args.out:
        set_base_dir(Path(args.out))
    check_writable()
    log(f"writing to {BASE_DIR / 'data'}")

    from playwright.sync_api import sync_playwright

    regions = [r.strip() for r in args.regions.split(",") if r.strip() in MARKET_PREFIX]
    todo: list[tuple[str, str]] = []

    # Resolve the symbol lists first, in one short-lived browser. Harvesting the listing here
    # is what lets this run on a machine with nothing but the script.
    with sync_playwright() as p:
        browser, _ctx, page = open_browser(p, args.headless, args.slow_mo)
        for region in regions:
            if args.symbols:
                wanted = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
                for sym in wanted:
                    for name in STATEMENTS:   # a forced refresh must clear the skip
                        (OUT_DIR / region / f"{sym}_{name}.csv").unlink(missing_ok=True)
                todo += [(region, s) for s in wanted]
                continue
            syms = load_symbols(page, region, args.symbols_file)
            if not syms:
                log(f"{region}: no symbols - skipping")
                continue
            todo += [(region, s) for s in syms
                     if _clean(s).isalnum() and not already_done(region, s)]
        browser.close()

    if args.limit:
        todo = todo[: args.limit]
    if not todo:
        log("nothing to do - everything already downloaded")
        return 0
    if args.workers > 1 and not args.headless:
        log(f"note: {args.workers} workers means {args.workers} browser windows")
    log(f"=== start: {len(todo)} symbols across {regions} "
        f"({args.workers} workers, {'headless' if args.headless else 'visible browser'}, "
        f"work {args.work}m / rest {args.rest}m) ===")

    state = {"idx": 0, "done": 0, "failed": 0}
    lock = threading.Lock()

    def worker(cycle_end: float) -> None:
        with sync_playwright() as p:
            browser, ctx, page = open_browser(p, args.headless, args.slow_mo)
            try:
                while True:
                    with lock:
                        if state["idx"] >= len(todo) or time.time() >= cycle_end:
                            break
                        i = state["idx"]
                        state["idx"] += 1
                    region, sym = todo[i]
                    try:
                        key = ("done" if scrape_symbol(page, region, sym, args.page_pause)
                               else "failed")
                    except Exception as exc:  # noqa: BLE001
                        key = "failed"
                        log(f"  {region}/{sym}: {type(exc).__name__}: {exc}")
                        # A crashed or closed tab poisons every later symbol on this worker, so
                        # rebuild it rather than logging thousands of identical failures.
                        if page.is_closed() or "closed" in str(exc).lower() or                                 "crash" in str(exc).lower():
                            log("  browser tab died - reopening")
                            try:
                                browser.close()
                            except Exception:  # noqa: BLE001
                                pass
                            browser, ctx, page = open_browser(
                                p, args.headless, args.slow_mo)
                    with lock:
                        state[key] += 1
                        seen = state["idx"]
                    if seen % 50 == 0:
                        log(f"  progress {seen}/{len(todo)} | saved {state['done']} "
                            f"| no-data {state['failed']}")
            finally:
                try:
                    browser.close()
                except Exception:  # noqa: BLE001
                    pass

    while state["idx"] < len(todo):
        cycle_end = time.time() + args.work * 60
        if args.workers <= 1:
            # Run in the MAIN thread. Playwright's sync API is greenlet-based and threads are
            # the fragile part of this design; with one worker a thread buys nothing and only
            # adds that risk. This is the shape of the PSX script that has been working all
            # along - one Playwright, one browser, one page, sequential.
            worker(cycle_end)
        else:
            threads = [threading.Thread(target=worker, args=(cycle_end,), daemon=True)
                       for _ in range(args.workers)]
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
    # A crash must leave evidence. Without this the run dies with a traceback in a console
    # window that gets closed, and "it crashed" is all anyone can say afterwards - which is
    # exactly what happened. The log file survives the window.
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("interrupted - progress is on disk, rerun to resume")
        sys.exit(130)
    except Exception:  # noqa: BLE001
        log("CRASHED:\n" + traceback.format_exc())
        log(f"full traceback written to {LOG_FILE}")
        input("Press Enter to close...")   # keep the window open so the error is readable
        sys.exit(1)
