"""Optional PSX financials scraper (stockanalysis.com) — populates the CSV folder.

This is the user's working Playwright scraper, adapted to write into the folder the
backend ingests (``AERP_PSX_CSV_DIR``, default ``data/psx_csv``). It is deliberately
kept OUT of the backend/worker image: Playwright needs a headless browser, so run it
as a standalone job (locally or on a schedule) to refresh the CSVs, and the light
in-platform ``ingest_psx_csv`` task loads whatever is present.

Setup:
    pip install playwright pandas
    playwright install chromium

Usage:
    AERP_PSX_CSV_DIR=data/psx_csv python scripts/scrape_psx.py
"""

from __future__ import annotations

import logging
import os

import pandas as pd
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

DATA_DIR = os.environ.get("AERP_PSX_CSV_DIR", "data/psx_csv")
os.makedirs(DATA_DIR, exist_ok=True)

LIST_URL = "https://stockanalysis.com/list/pakistan-stock-exchange/"
STATEMENTS = {
    "Income_Statement": "financials",
    "Balance_Sheet": "financials/balance-sheet",
    "Cash_Flow": "financials/cash-flow-statement",
    "Ratios": "financials/ratios",
}
FALLBACK_SYMBOLS = ["SYS", "ENGROH", "HUBC", "LUCK", "MCB", "OGDC", "PPL", "EFERT"]


def harvest_symbols(page) -> list[str]:
    try:
        page.goto(LIST_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        page.wait_for_selector("table", timeout=15000)
        raw = page.locator("table tbody tr td a[href*='/quote/psx/']").all_inner_texts()
        symbols = sorted({
            t.strip().upper() for t in raw
            if t.strip() and t.strip().isalnum() and len(t.strip()) <= 7 and not t.strip().isdigit()
        })
        if symbols:
            logging.info("Extracted %d PSX symbols", len(symbols))
            return symbols
    except Exception as exc:  # noqa: BLE001
        logging.error("Symbol harvest failed: %s", exc)
    logging.warning("Falling back to baseline symbol set")
    return FALLBACK_SYMBOLS


def scrape_table(page, url: str) -> pd.DataFrame | None:
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2000)
        if not resp or resp.status >= 400:
            return None
        page.wait_for_selector("table", timeout=10000)
        table = page.locator("table[data-test='financials-table']").or_(page.locator("table")).first
        if table.count() == 0:
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
            if len(cells) == len(headers) * 2:
                cells = cells[: len(headers)]
            elif len(cells) != len(headers):
                cells = cells[: len(headers)] + [""] * max(0, len(headers) - len(cells))
            rows.append(cells)
        return pd.DataFrame(rows, columns=headers) if rows else None
    except Exception:  # noqa: BLE001
        return None


def process_symbol(page, symbol: str) -> None:
    for name, path in STATEMENTS.items():
        csv_file = os.path.join(DATA_DIR, f"{symbol}_{name}.csv")
        if os.path.exists(csv_file) and os.path.getsize(csv_file) > 10:
            continue  # incremental cache: skip already-downloaded files
        url = f"https://stockanalysis.com/quote/psx/{symbol}/{path}/?p=trailing"
        df = scrape_table(page, url)
        if df is not None and not df.empty:
            df.fillna("", inplace=True)
            df.to_csv(csv_file, index=False, encoding="utf-8")
            logging.info("Saved %s_%s.csv", symbol, name)
        page.wait_for_timeout(1000)


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 850},
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
        )
        page = context.new_page()
        symbols = harvest_symbols(page)
        logging.info("Processing %d symbols → %s", len(symbols), DATA_DIR)
        for i, symbol in enumerate(symbols, 1):
            logging.info("[%d/%d] %s", i, len(symbols), symbol)
            try:
                process_symbol(page, symbol)
            except Exception as exc:  # noqa: BLE001
                logging.error("Skipping %s: %s", symbol, exc)
            page.wait_for_timeout(1000)
        browser.close()
    logging.info("Done. CSVs in %s", DATA_DIR)


if __name__ == "__main__":
    main()
