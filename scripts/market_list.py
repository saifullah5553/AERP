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

# Read columns by their header, not by position: the table's columns change with whatever
# indicators are enabled, so fixed indices would silently pick up the wrong field.
_EXTRACT = """() => {
    const tables = [...document.querySelectorAll('table')];
    if (!tables.length) return [];
    const t = tables.reduce((a, b) =>
        b.querySelectorAll('tbody tr').length > a.querySelectorAll('tbody tr').length ? b : a);
    const heads = [...t.querySelectorAll('thead th')].map(h => h.innerText.trim().toLowerCase());
    const idx = name => heads.findIndex(h => h === name);
    const iSym = idx('symbol'), iName = idx('company name');
    const iSec = idx('sector'), iInd = idx('industry');
    if (iSym < 0) return [];
    return [...t.querySelectorAll('tbody tr')].map(r => {
        const tds = [...r.querySelectorAll('td')].map(c => c.innerText.trim());
        const at = i => (i >= 0 && i < tds.length) ? tds[i] : '';
        return [at(iSym), at(iName), at(iSec), at(iInd)];
    }).filter(x => x[0]);
}"""


def _enable_sector_columns(page) -> bool:
    """Turn on the Sector and Industry columns via the Indicators chooser.

    stockanalysis carries a sector for every market, including India - where the NSE feed has
    none - so taking it from the same listing we already paginate is both authoritative and
    free. Best-effort: if the control moves, the run still returns symbols and names.
    """
    try:
        page.locator("button:has-text('Indicators')").first.click()
        page.wait_for_timeout(1200)
        for label in ("Sector", "Industry"):
            opt = page.get_by_text(label, exact=True)
            if opt.count():
                opt.first.click()
                page.wait_for_timeout(600)
        page.keyboard.press("Escape")
        page.wait_for_timeout(1200)
        heads = page.evaluate(
            "() => [...document.querySelectorAll('thead th')]"
            ".map(h => h.innerText.trim().toLowerCase())"
        )
        return "sector" in heads
    except Exception:  # noqa: BLE001 - the list is still useful without sectors
        return False


def fetch(region: str) -> list[tuple[str, str]]:
    from playwright.sync_api import sync_playwright

    url = LISTS[region]
    rows: dict[str, tuple[str, str, str]] = {}
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
            if not _enable_sector_columns(page):
                print(f"  {region}: sector columns unavailable - names only")

            for _ in range(MAX_PAGES):
                page_rows = page.evaluate(_EXTRACT)
                for sym, name, sector, industry in page_rows:
                    sym = (sym or "").strip().upper()
                    if sym:
                        rows.setdefault(sym, ((name or "").strip() or sym,
                                              (sector or "").strip(),
                                              (industry or "").strip()))
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
            w.writerow(["symbol", "name", "sector", "industry"])
            for sym, (name, sector, industry) in listed:
                w.writerow([sym, name, sector, industry])
        with_sector = sum(1 for _s, (_n, sec, _i) in listed if sec)
        print(f"{region}: {len(listed)} symbols ({with_sector} with sector) "
              f"-> {path.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
