"""Render the per-market scrapers from _template.py.

The six scrapers are the same program with a different exchange bolted on. They were
originally copied by hand, which meant a fix to one - the resume logic, the split-table
extractor, the pacing - silently left the other five behind. Edit _template.py, run this,
commit the result:

    python scripts/market_scrapers/generate.py

The generated files stay checked in on purpose: they are what actually gets run, on a machine
that has playwright and pandas and nothing else from this repo.
"""

from __future__ import annotations

import os

BASE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(BASE, "_template.py")

PLAIN_SLUG = '    return symbol.strip().upper()'

MARKETS = [
    {
        "script": "scrape_us.py",
        "name": "US",
        "market": "us",
        "out": "us_data",
        "list_url": "https://stockanalysis.com/stocks/",
        "quote_prefix": "stocks",
        "slug": ("    # SEC writes class shares with a dash; stockanalysis uses a dot.\n"
                 '    return symbol.strip().upper().replace("-", ".")'),
    },
    {
        "script": "scrape_india.py",
        "name": "India (NSE)",
        "market": "india",
        "out": "india_data",
        "list_url": "https://stockanalysis.com/list/nse-india/",
        "quote_prefix": "quote/nse",
        "slug": ('    # NSE\'s "-" and "&" both become "_" (BAJAJ-AUTO -> BAJAJ_AUTO).\n'
                 '    return symbol.strip().upper().replace("-", "_").replace("&", "_")'),
    },
    {
        "script": "scrape_psx.py",
        "name": "Pakistan (PSX)",
        "market": "psx",
        "out": "psx_data",
        "list_url": "https://stockanalysis.com/list/pakistan-stock-exchange/",
        "quote_prefix": "quote/psx",
        "slug": PLAIN_SLUG,
    },
    {
        "script": "scrape_australia.py",
        "name": "Australia (ASX)",
        "market": "australia",
        "out": "australia_data",
        "list_url": "https://stockanalysis.com/list/australian-securities-exchange/",
        "quote_prefix": "quote/asx",
        "slug": PLAIN_SLUG,
    },
    {
        "script": "scrape_tadawul.py",
        "name": "Saudi (Tadawul)",
        "market": "gcc",
        "out": "tadawul_data",
        "list_url": "https://stockanalysis.com/list/saudi-stock-exchange/",
        "quote_prefix": "quote/tadawul",
        "slug": PLAIN_SLUG,
    },
    {
        "script": "scrape_dfm.py",
        "name": "Dubai (DFM)",
        "market": "dfm",
        "out": "dfm_data",
        "list_url": "https://stockanalysis.com/list/dubai-financial-market/",
        "quote_prefix": "quote/dfm",
        "slug": PLAIN_SLUG,
    },
]


def main() -> None:
    with open(TEMPLATE, encoding="utf-8") as fh:
        template = fh.read()

    for m in MARKETS:
        body = (template
                .replace("@@MARKET_NAME@@", m["name"])
                .replace("@@SCRIPT_NAME@@", m["script"])
                .replace("@@OUT_NAME@@", m["out"])
                .replace("@@MARKET@@", m["market"])
                .replace("@@LIST_URL@@", m["list_url"])
                .replace("@@QUOTE_PREFIX@@", m["quote_prefix"])
                .replace("@@SLUG_BODY@@", m["slug"]))
        if "@@" in body:
            leftover = body[body.index("@@"):][:40]
            raise SystemExit(f"{m['script']}: unsubstituted placeholder near {leftover!r}")
        with open(os.path.join(BASE, m["script"]), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(body)
        print(f"wrote {m['script']}")


if __name__ == "__main__":
    main()
