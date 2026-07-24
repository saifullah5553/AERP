"""Optional PSX insider-transactions scraper (Sarmaaya) → CSV for the backend.

Sarmaaya's insider-transactions view is a Next.js app with no public JSON API, so
this uses Playwright (a real browser) — kept OUT of the backend image, exactly like
scrape_psx.py. It writes a CSV that ``ingest_psx_insider`` loads into the shared
insider engine (which computes the 60-day buy/sell score for PSX just like US).

IMPORTANT — needs finalising against the live site: the table selectors and column
order below are a best-effort starting point. Run it with a visible browser once
(headless=False) to confirm the row/cell structure, then adjust SELECTORS/columns.
The backend's CSV parser matches headers flexibly, so only the header names need to
line up with: symbol, insider, title, date, type, shares, price.

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
URL = "https://sarmaaya.pk/announcements"
HEADER = ["symbol", "insider", "title", "date", "type", "shares", "price"]


def scrape_rows(page) -> list[list[str]]:
    """Best-effort extraction of the insider-transactions table.

    Adjust the selectors after inspecting the live DOM (the tab is a radio button
    labelled 'insider transactions'; the table renders below it).
    """
    page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)
    # Switch to the Insider Transactions tab.
    try:
        page.get_by_role("radio", name="insider transactions").click()
        page.wait_for_timeout(2500)
    except Exception as exc:  # noqa: BLE001
        logging.warning("Could not click the insider tab: %s", exc)

    rows: list[list[str]] = []
    for tr in page.locator("table tbody tr").all():
        cells = [c.strip() for c in tr.locator("td").all_inner_texts()]
        if cells:
            rows.append(cells)
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
        # NOTE: reorder/select cells to match HEADER once the live layout is confirmed.
        for r in rows:
            w.writerow(r[: len(HEADER)] + [""] * max(0, len(HEADER) - len(r)))
    logging.info("Wrote %s", OUT_CSV)


if __name__ == "__main__":
    main()
