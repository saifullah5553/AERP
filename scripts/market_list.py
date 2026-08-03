"""Pull a market's full listed-company list from stockanalysis.

Why this exists alongside the exchange feeds: the NSE archive we build the Indian universe from
only carries the EQ series, so it lists ~2,050 companies where stockanalysis lists 3,020. The
extra names are real companies with real statements - and since fundamentals come from
stockanalysis, a name it lists is a name we can actually score.

Writes data/universe/<region>.csv (symbol,name), which expand_universe unions with the
exchange feed. Small enough to version, so CI needs no scraping to know the universe.

    python scripts/market_list.py india
    python scripts/market_list.py india australia
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "data" / "universe"

# The list pages show 500 rows at a time behind a Next button.
LISTS = {
    "india": "https://stockanalysis.com/list/nse-india/",
    "australia": "https://stockanalysis.com/list/australian-securities-exchange/",
    "psx": "https://stockanalysis.com/list/pakistan-stock-exchange/",
}
MAX_PAGES = 30
SKIP_RESOURCES = {"image", "media", "font", "stylesheet"}

_EXTRACT = """() => {
    const tables = [...document.querySelectorAll('table')];
    if (!tables.length) return [];
    const t = tables.reduce((a, b) =>
        b.querySelectorAll('tbody tr').length > a.querySelectorAll('tbody tr').length ? b : a);
    return [...t.querySelectorAll('tbody tr')].map(r => {
        const tds = [...r.querySelectorAll('td')].map(c => c.innerText.trim());
        // Columns are: No. | Symbol | Company Name | ...
        return tds.length >= 3 ? [tds[1], tds[2]] : null;
    }).filter(Boolean);
}"""


def fetch(region: str) -> list[tuple[str, str]]:
    from playwright.sync_api import sync_playwright

    url = LISTS[region]
    rows: dict[str, str] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            ctx = browser.new_context(
                user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
            )
            ctx.route(
                "**/*",
                lambda route: route.abort()
                if route.request.resource_type in SKIP_RESOURCES
                else route.continue_(),
            )
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_function(
                "() => [...document.querySelectorAll('table')]"
                ".some(t => t.querySelectorAll('tbody tr').length > 10)",
                timeout=25000,
            )

            for _ in range(MAX_PAGES):
                page_rows = page.evaluate(_EXTRACT)
                for sym, name in page_rows:
                    sym = (sym or "").strip().upper()
                    if sym:
                        rows.setdefault(sym, (name or "").strip() or sym)
                # "Next" is a link on these pages, not a button - get_by_role("button")
                # silently matches nothing and the fetch quietly stops at the first 500.
                nxt = page.locator("button:has-text('Next'), a:has-text('Next')")
                if nxt.count() == 0 or not nxt.first.is_enabled():
                    break
                # The table re-renders in place - there is no navigation to await. A fixed
                # wait truncated the fetch at 1000 of 3020 the moment a page took longer than
                # the guess, and truncation here looks exactly like "that's the whole market".
                head = page_rows[0][0] if page_rows else ""
                nxt.first.click()
                try:
                    page.wait_for_function(
                        """h => {
                            const ts = [...document.querySelectorAll('table')];
                            if (!ts.length) return false;
                            const t = ts.reduce((a, b) =>
                                b.querySelectorAll('tbody tr').length >
                                a.querySelectorAll('tbody tr').length ? b : a);
                            const c = t.querySelector('tbody tr td:nth-child(2)');
                            return !!c && c.innerText.trim() !== h;
                        }""",
                        arg=head, timeout=20000,
                    )
                except Exception:  # noqa: BLE001 - last page, or the table stopped changing
                    break
        finally:
            browser.close()
    return sorted(rows.items())


def main(argv: list[str]) -> int:
    regions = [a for a in argv if a in LISTS] or ["india"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for region in regions:
        listed = fetch(region)
        if not listed:
            print(f"{region}: nothing fetched (rate limited?) - leaving existing file alone")
            continue
        path = OUT_DIR / f"{region}.csv"
        with open(path, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["symbol", "name"])
            w.writerows(listed)
        print(f"{region}: {len(listed)} symbols -> {path.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
