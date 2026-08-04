"""Download Dubai (DFM) financial statements from stockanalysis.com.

Simple and self-contained. One browser, one page, one symbol at a time.

    pip install playwright pandas
    python -m playwright install chromium
    python scrape_dfm.py

Flow: open the list page -> collect every symbol -> for each symbol open its four
statement pages (income, balance sheet, cash flow, ratios) at ?p=trailing and save each table.

Output goes NEXT TO THIS SCRIPT in dfm_data/, never into the folder you launched from -
creating a folder in the Windows user profile is refused by Controlled Folder Access.

Resumable: a statement whose CSV already exists is skipped, so stop and restart freely.

Two details that matter, both of which fail silently if you change them:

  * The statement is at the EXPLICIT path ("financials/income-statement"). Bare "financials"
    is a landing page with a condensed 7-row summary that parses fine and is wrong.
  * A statement is SPLIT ACROSS SEVERAL TABLES sharing one period grid - a balance sheet
    arrives as assets / liabilities / equity. Taking the biggest table alone captured only the
    assets half of 74 of 160 Indian balance sheets, with nothing downstream able to tell.
"""

from __future__ import annotations

import csv
import os
import random
import time

import pandas as pd
from playwright.sync_api import sync_playwright

MARKET = "dfm"
LIST_URL = "https://stockanalysis.com/list/dubai-financial-market/"
QUOTE_PREFIX = "quote/dfm"      # stockanalysis path for this exchange

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "dfm_data")
SYMBOL_FILE = os.path.join(DATA_DIR, "_symbols.csv")
# Why a symbol produced nothing. The distinction cannot be recovered afterwards, and it
# matters: "no financials page exists" is a permanent fact about the company, while "the fetch
# failed" is about this run. Excluding a real company from the platform because of a timeout
# would be a silent, permanent loss.
NO_DATA_FILE = os.path.join(DATA_DIR, "_no_data.csv")
os.makedirs(DATA_DIR, exist_ok=True)

STATEMENTS = {
    "Income_Statement": "financials/income-statement",
    "Balance_Sheet": "financials/balance-sheet",
    "Cash_Flow": "financials/cash-flow-statement",
    "Ratios": "financials/ratios",
}

# Pacing. Slower than feels necessary on purpose: stockanalysis starts serving a "verify you
# are human" challenge when requests arrive at a machine-like rate, and a challenge costs far
# more than the seconds saved - the page returns no table, and without the check below the
# company is silently skipped as if it had no financials.
PAGE_PAUSE = 3.0          # seconds between statement pages
SYMBOL_PAUSE = 4.0        # seconds between companies
JITTER = 0.6              # +/- fraction, so the rhythm is not perfectly regular
BREATHER_EVERY = 40       # companies
BREATHER_SECONDS = 90

MIN_ROWS = 12         # a real statement has ~30 rows; less means a summary or a half-load
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def pause(seconds):
    """Sleep with jitter. A perfectly regular interval is itself a bot signal."""
    time.sleep(max(0.2, seconds * (1 + random.uniform(-JITTER, JITTER))))


# Text that appears on the challenge page instead of the data.
CHALLENGE_MARKERS = (
    "verify you are human", "are you a robot", "not a robot", "just a moment",
    "checking your browser", "cloudflare", "captcha", "unusual traffic",
)


def is_challenged(page):
    """Is the site asking us to prove we are human?

    Worth detecting explicitly: a challenge page has no statement table, so it is otherwise
    indistinguishable from a company that files nothing - and that would quietly drop a real
    company from the platform.
    """
    try:
        body = (page.inner_text("body") or "").lower()[:4000]
    except Exception:
        return False
    return any(marker in body for marker in CHALLENGE_MARKERS)


def wait_out_challenge(page, minutes=10):
    """Stop and let a human clear the check in the visible browser window.

    The browser is deliberately not headless, so the check is solvable: solve it once and the
    run continues. Waiting beats skipping - a skipped company is data we never come back for.
    """
    print("\n" + "=" * 70)
    print("  The site is asking to verify you are human.")
    print("  Solve the check in the browser window - the run continues automatically.")
    print(f"  Waiting up to {minutes} minutes...")
    print("=" * 70 + "\n")
    deadline = time.time() + minutes * 60
    while time.time() < deadline:
        page.wait_for_timeout(3000)
        if not is_challenged(page):
            print("  Check cleared, continuing.\n")
            pause(5)
            return True
    print("  Still challenged after waiting. Stopping so nothing is skipped silently.\n")
    return False


def symbol_to_slug(symbol):
    """stockanalysis spells some tickers differently from the exchange."""
    return symbol.strip().upper()


# Read every table that shares the widest table's column count, and dedupe by row label.
# That is what reassembles a statement split across several tables.
EXTRACT_JS = """() => {
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

LIST_JS = """() => {
    const tables = [...document.querySelectorAll('table')];
    if (!tables.length) return [];
    const t = tables.reduce((a, b) =>
        b.querySelectorAll('tbody tr').length > a.querySelectorAll('tbody tr').length ? b : a);
    const heads = [...t.querySelectorAll('thead th')].map(h => h.innerText.trim().toLowerCase());
    let i = heads.indexOf('symbol');
    if (i < 0) i = heads.length > 1 ? 1 : 0;
    return [...t.querySelectorAll('tbody tr')]
        .map(r => {
            const tds = [...r.querySelectorAll('td')].map(c => c.innerText.trim());
            return i < tds.length ? tds[i] : '';
        }).filter(Boolean);
}"""


def collect_symbols(page):
    """Every listed symbol, paging through the list 500 at a time. Cached after the first run."""
    if os.path.exists(SYMBOL_FILE):
        with open(SYMBOL_FILE, encoding="utf-8") as fh:
            syms = [r["symbol"] for r in csv.DictReader(fh) if r.get("symbol")]
        if syms:
            print(f"Using {len(syms)} cached symbols from {SYMBOL_FILE}")
            return syms

    print(f"Opening {LIST_URL}")
    page.goto(LIST_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_selector("table tbody tr", timeout=30000)
    page.wait_for_timeout(2000)

    # The page states its own size ("383 Stocks"). Use it as the bound: past the last page the
    # "Next" control can lead somewhere else entirely - following it once collected 600 US
    # tickers into a Saudi list.
    declared = page.evaluate(
        r"""() => {
            const m = document.body.innerText.match(/([0-9][0-9,]*)\s+[Ss]tocks?\b/);
            return m ? parseInt(m[1].replace(/,/g, ''), 10) : null;
        }"""
    )
    print(f"Listing declares {declared} stocks")

    symbols, seen = [], set()
    for _ in range(40):
        rows = page.evaluate(LIST_JS)
        for sym in rows:
            s = sym.strip().upper()
            if s and s not in seen:
                seen.add(s)
                symbols.append(s)
        print(f"  collected {len(symbols)}")
        if declared and len(symbols) >= declared:
            break
        nxt = page.locator("a:has-text('Next'), button:has-text('Next')")
        if nxt.count() == 0 or not nxt.first.is_enabled():
            break
        first_before = rows[0] if rows else ""
        try:
            nxt.first.click(timeout=20000)
            # Wait for the table to actually change. A fixed pause stopped this at 1,000 of
            # 3,020 Indian names the moment a page rendered slowly.
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
                    const tds = [...t.querySelector('tbody tr').querySelectorAll('td')];
                    return i < tds.length && tds[i].innerText.trim() !== h;
                }""",
                arg=first_before, timeout=30000,
            )
        except Exception as exc:
            print(f"  stopped paging: {type(exc).__name__}")
            break
        page.wait_for_timeout(1000)

    if declared and len(symbols) > declared:
        symbols = symbols[:declared]
    if declared and len(symbols) < declared:
        print(f"  WARNING: got {len(symbols)} of {declared}. "
              f"Delete {SYMBOL_FILE} and rerun to try again.")

    with open(SYMBOL_FILE, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["symbol"])
        w.writerows([[s] for s in symbols])
    print(f"Saved {len(symbols)} symbols to {SYMBOL_FILE}")
    return symbols


def record_no_data(symbol, statement, reason):
    """Note why a statement was not saved, so exclusions can later be based on evidence."""
    new = not os.path.exists(NO_DATA_FILE)
    with open(NO_DATA_FILE, "a", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["symbol", "statement", "reason"])
        w.writerow([symbol, statement, reason])


def scrape_statement(page, url):
    """The statement table at `url`. Returns (dataframe_or_None, reason)."""
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=60000)
        if resp and resp.status == 404:
            # "This stock exists, but the specific page type was not found." A permanent fact
            # about the company - shells, SPACs and trusts file no statements.
            return None, "no_financials_page"
        if not resp or resp.status >= 400:
            if resp and resp.status == 429 and is_challenged(page):
                return None, "bot_check"
            return None, f"http_{resp.status if resp else 'none'}"
        if is_challenged(page):
            return None, "bot_check"
        page.wait_for_selector("table tbody tr", timeout=30000)
        page.wait_for_timeout(1500)      # let the rest of the table render

        data = page.evaluate(EXTRACT_JS)
        if not data or not data["headers"] or not data["rows"]:
            return None, "empty_table"
        headers, rows = data["headers"], []
        for cells in data["rows"]:
            if len(cells) == len(headers) * 2:        # some rows repeat the label column
                cells = cells[: len(headers)]
            elif len(cells) != len(headers):
                cells = cells[: len(headers)] + [""] * max(0, len(headers) - len(cells))
            rows.append(cells)
        if len(rows) < MIN_ROWS:
            return None, "too_few_rows"
        return pd.DataFrame(rows, columns=headers), "ok"
    except Exception as exc:
        # A challenge page has no table, so the selector wait times out - check before
        # reporting this as "the company has nothing".
        if is_challenged(page):
            return None, "bot_check"
        print(f"      {type(exc).__name__}")
        return None, type(exc).__name__


def already_done(symbol):
    """Are all four statements already on disk for this company?"""
    return all(
        os.path.exists(os.path.join(DATA_DIR, f"{symbol}_{name}.csv"))
        and os.path.getsize(os.path.join(DATA_DIR, f"{symbol}_{name}.csv")) > 10
        for name in STATEMENTS
    )


def scrape_symbol(page, symbol):
    saved = 0
    for name, path in STATEMENTS.items():
        csv_file = os.path.join(DATA_DIR, f"{symbol}_{name}.csv")
        if os.path.exists(csv_file) and os.path.getsize(csv_file) > 10:
            saved += 1
            continue
        url = (f"https://stockanalysis.com/{QUOTE_PREFIX}/"
               f"{symbol_to_slug(symbol)}/{path}/?p=trailing")
        df, reason = scrape_statement(page, url)
        if reason == "bot_check":
            # Do NOT record this as missing data: the company may well file statements, we were
            # simply stopped. Wait for a human, then retry this same statement once.
            if not wait_out_challenge(page):
                raise RuntimeError("blocked by human-verification check")
            df, reason = scrape_statement(page, url)
        if df is not None and not df.empty:
            df.fillna("", inplace=True)
            df.to_csv(csv_file, index=False, encoding="utf-8")
            print(f"    saved {name} ({len(df)} rows)")
            saved += 1
        else:
            print(f"    no {name} ({reason})")
            record_no_data(symbol, name, reason)
        pause(PAGE_PAUSE)
    return saved


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,          # a real window: you can see what the site is doing
            slow_mo=100,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        page = browser.new_context(
            viewport={"width": 1440, "height": 900}, user_agent=UA
        ).new_page()

        symbols = collect_symbols(page)

        # Drop what is already downloaded BEFORE the loop, not inside it. Skipping a finished
        # company still cost a printed line and the full inter-company pause, so restarting
        # with 2,000 done sat for over two hours doing nothing before reaching new work -
        # which looks exactly like starting from zero.
        total = len(symbols)
        symbols = [s for s in symbols if not already_done(s)]
        print(f"\nDubai (DFM): {total} symbols, {total - len(symbols)} already "
              f"downloaded, {len(symbols)} to go.")
        print(f"Writing to {DATA_DIR}\n")
        if not symbols:
            print("Nothing left to fetch.")
            browser.close()
            return

        for i, symbol in enumerate(symbols, 1):
            print(f"[{i}/{len(symbols)}] {symbol}")
            try:
                scrape_symbol(page, symbol)
            except RuntimeError as exc:
                # Being blocked is not a per-company problem. Carrying on would fail every
                # remaining symbol and fill the skip list with companies that are fine.
                print(f"\nStopping: {exc}")
                print("Everything downloaded so far is saved. Rerun later to continue.\n")
                break
            except Exception as exc:
                print(f"    skipped: {type(exc).__name__}: {exc}")
            # A longer rest now and then, which is what a person browsing actually looks like.
            if i % BREATHER_EVERY == 0:
                print(f"  ...resting {BREATHER_SECONDS}s after {i} companies")
                time.sleep(BREATHER_SECONDS)
            else:
                pause(SYMBOL_PAUSE)

        browser.close()
    print(f"\\nDone. Files in {DATA_DIR}")


if __name__ == "__main__":
    main()
