"""Download Pakistan (PSX) financial statements from stockanalysis.com.

Simple and self-contained. One browser, one page, one symbol at a time.

    pip install playwright pandas
    python -m playwright install chromium
    python scrape_psx.py

Flow: open the list page -> collect every symbol -> for each symbol open its four
statement pages (income, balance sheet, cash flow, ratios) at ?p=trailing and save each table.

Output goes NEXT TO THIS SCRIPT in psx_data/, never into the folder you launched from -
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
import time

import pandas as pd
from playwright.sync_api import sync_playwright

MARKET = "psx"
LIST_URL = "https://stockanalysis.com/list/pakistan-stock-exchange/"
QUOTE_PREFIX = "quote/psx"      # stockanalysis path for this exchange

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "psx_data")
SYMBOL_FILE = os.path.join(DATA_DIR, "_symbols.csv")
os.makedirs(DATA_DIR, exist_ok=True)

STATEMENTS = {
    "Income_Statement": "financials/income-statement",
    "Balance_Sheet": "financials/balance-sheet",
    "Cash_Flow": "financials/cash-flow-statement",
    "Ratios": "financials/ratios",
}

PAGE_PAUSE = 1.5      # seconds between page loads - be a polite guest
MIN_ROWS = 12         # a real statement has ~30 rows; less means a summary or a half-load
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


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


def scrape_statement(page, url):
    """The statement table at `url`, or None."""
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=60000)
        if not resp or resp.status >= 400:
            return None            # 404 here means the company has no such page (SPACs, shells)
        page.wait_for_selector("table tbody tr", timeout=30000)
        page.wait_for_timeout(1500)      # let the rest of the table render

        data = page.evaluate(EXTRACT_JS)
        if not data or not data["headers"] or not data["rows"]:
            return None
        headers, rows = data["headers"], []
        for cells in data["rows"]:
            if len(cells) == len(headers) * 2:        # some rows repeat the label column
                cells = cells[: len(headers)]
            elif len(cells) != len(headers):
                cells = cells[: len(headers)] + [""] * max(0, len(headers) - len(cells))
            rows.append(cells)
        if len(rows) < MIN_ROWS:
            return None
        return pd.DataFrame(rows, columns=headers)
    except Exception as exc:
        print(f"      {type(exc).__name__}")
        return None


def scrape_symbol(page, symbol):
    saved = 0
    for name, path in STATEMENTS.items():
        csv_file = os.path.join(DATA_DIR, f"{symbol}_{name}.csv")
        if os.path.exists(csv_file) and os.path.getsize(csv_file) > 10:
            saved += 1
            continue
        url = (f"https://stockanalysis.com/{QUOTE_PREFIX}/"
               f"{symbol_to_slug(symbol)}/{path}/?p=trailing")
        df = scrape_statement(page, url)
        if df is not None and not df.empty:
            df.fillna("", inplace=True)
            df.to_csv(csv_file, index=False, encoding="utf-8")
            print(f"    saved {name} ({len(df)} rows)")
            saved += 1
        else:
            print(f"    no {name}")
        time.sleep(PAGE_PAUSE)
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
        print(f"\nPakistan (PSX): {len(symbols)} symbols. Writing to {DATA_DIR}\n")

        for i, symbol in enumerate(symbols, 1):
            print(f"[{i}/{len(symbols)}] {symbol}")
            try:
                scrape_symbol(page, symbol)
            except Exception as exc:
                print(f"    skipped: {type(exc).__name__}: {exc}")
            time.sleep(PAGE_PAUSE)

        browser.close()
    print(f"\\nDone. Files in {DATA_DIR}")


if __name__ == "__main__":
    main()
