"""PSX insider-transactions scraper (Portfolio360) → CSV for the backend.

Portfolio360's insider page (https://portfolio360.app/markets/insider-transactions)
renders a clean table on load — Date, Symbol, Company, Person, Role, Type, Shares,
Rate, Value — with no tab/interaction needed, which makes it a reliable scrape
target. It's a React SPA, so this uses Playwright (a real browser); kept OUT of the
backend image, like scrape_psx.py. The CSV it writes is loaded by
``ingest_psx_insider`` into the shared insider engine (60-day buy/sell score).

The backend CSV parser matches headers flexibly, so the raw Portfolio360 column
names below (Symbol/Person/Role/Date/Type/Shares/Rate/Value) map automatically to
symbol/insider/title/date/type/shares/price/value.

Setup:
    pip install playwright
    playwright install chromium

Usage:
    AERP_PSX_INSIDER_CSV=data/psx_insider.csv python scripts/scrape_psx_insider.py
"""

from __future__ import annotations

import csv
import logging
import os

from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

OUT_CSV = os.environ.get("AERP_PSX_INSIDER_CSV", "data/psx_insider.csv")
URL = "https://portfolio360.app/markets/insider-transactions"
# Column order as rendered by Portfolio360's table.
HEADER = ["date", "symbol", "company", "person", "role", "type", "shares", "rate", "value"]


def scrape_rows(page) -> list[list[str]]:
    page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_selector("table tbody tr", timeout=20000)
    page.wait_for_timeout(1500)  # let the table finish populating
    rows: list[list[str]] = []
    for tr in page.locator("table tbody tr").all():
        cells = [c.strip() for c in tr.locator("td").all_inner_texts()]
        if len(cells) >= 8 and cells[0]:  # skip spacer/empty rows
            rows.append(cells[: len(HEADER)])
    return rows


def main() -> None:
    os.makedirs(os.path.dirname(OUT_CSV) or ".", exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        ).new_page()
        rows = scrape_rows(page)
        browser.close()

    logging.info("Scraped %d insider rows", len(rows))
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        for r in rows:
            w.writerow(r + [""] * max(0, len(HEADER) - len(r)))
    logging.info("Wrote %s", OUT_CSV)


if __name__ == "__main__":
    main()
