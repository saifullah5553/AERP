"""One canonical spelling per company, and the per-provider spellings derived from it.

Three sources disagree about how to write a ticker, and every disagreement fails silently:
a wrong spelling 404s, gets logged as "no data", and reads as a company that does not report.
427 US symbols and every Indian ampersand ticker were lost to exactly that before this existed.

The rules, established by querying each provider rather than assuming:

    case              exchange      yfinance          stockanalysis
    US class share    BRK-B         BRK-B             BRK.B
    India hyphen      BAJAJ-AUTO    BAJAJ-AUTO.NS     BAJAJ_AUTO
    India ampersand   M&M           M&M.NS            M_M
    Australia         BHP           BHP.AX            BHP
    PSX               LUCK          LUCK.KA           LUCK

So the exchange spelling is canonical, yfinance is that plus a market suffix, and only
stockanalysis needs transforming. Which matters for the division of labour: prices and daily
OHLC come from yfinance, fundamentals from stockanalysis, and the two must agree on which
company they are talking about.

stockanalysis collapses BOTH '-' and '&' to '_', so the transform is lossy in that direction -
`M_M` alone cannot tell you whether the exchange writes `M&M` or `M-M`. Never invert it by
guessing; match through `norm_key`, or use the real listed slug from data/universe/<region>.csv.
"""

from __future__ import annotations

import csv
from pathlib import Path

from app.core.logging import get_logger

log = get_logger(__name__)

DATA = Path(__file__).resolve().parents[3] / "data"
LISTED_DIR = DATA / "universe"
OUT_DIR = DATA / "symbols"

# Suffix yfinance appends per market. US is bare.
YAHOO_SUFFIX = {
    "us": "",
    "india": ".NS",
    "australia": ".AX",
    "psx": ".KA",
    "gcc": ".SR",
}

# URL prefix stockanalysis uses per market. GCC is absent - it does not carry Tadawul.
SA_PREFIX = {
    "us": "stocks",
    "india": "quote/nse",
    "australia": "quote/asx",
    "psx": "quote/psx",
}


def yahoo(region: str, symbol: str) -> str:
    """The yfinance / Yahoo chart symbol - exchange spelling plus the market suffix."""
    return f"{symbol.strip().upper()}{YAHOO_SUFFIX.get(region, '')}"


def stockanalysis(region: str, symbol: str) -> str:
    """The stockanalysis slug for an exchange symbol."""
    sym = symbol.strip().upper()
    if region == "us":
        # SEC writes class shares with a dash; stockanalysis uses a dot.
        return sym.replace("-", ".")
    if region == "india":
        # NSE's '-' and '&' both become '_'.
        return sym.replace("-", "_").replace("&", "_")
    return sym


def norm_key(symbol: str) -> str:
    """Comparison key that survives every provider's spelling of the same ticker."""
    s = symbol.strip().upper()
    for ch in "-&.":
        s = s.replace(ch, "_")
    return s


def listed_slugs(region: str, listed_dir: Path | None = None) -> dict[str, str]:
    """{norm_key: actual slug} from the captured listing, when we have one.

    Preferred over the transform where available: it is what the site really serves, so a
    market with an exception we have not met yet still resolves.
    """
    path = (listed_dir or LISTED_DIR) / f"{region}.csv"
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    with open(path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            sym = (row.get("symbol") or "").strip().upper()
            if sym:
                out[norm_key(sym)] = sym
    return out


def resolve(region: str, symbol: str, slugs: dict[str, str] | None = None) -> dict[str, str]:
    """Every provider's spelling for one company."""
    sym = symbol.strip().upper()
    sa = (slugs or {}).get(norm_key(sym)) or stockanalysis(region, sym)
    return {
        "region": region,
        "symbol": sym,                      # canonical: the exchange's own spelling
        "yahoo": yahoo(region, sym),        # prices and daily OHLC
        "stockanalysis": sa,                # fundamentals
    }


def build_registry(rows: list[dict], out_dir: Path | None = None,
                   listed_dir: Path | None = None) -> dict[str, int]:
    """Write data/symbols/<region>.csv for every company, one row per security.

    `rows` are screener-shaped dicts (region, symbol, name). Materialising this rather than
    only computing it on the fly means a mismatch can be diffed and reviewed instead of being
    discovered as an unexplained gap months later.
    """
    out = out_dir or OUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    by_region: dict[str, list[dict]] = {}
    for r in rows:
        region = r.get("region")
        sym = (r.get("symbol") or "").strip().upper()
        if not region or not sym or region not in YAHOO_SUFFIX:
            continue
        by_region.setdefault(region, []).append(
            {**r, "symbol": sym, "name": (r.get("name") or "").strip()}
        )

    counts: dict[str, int] = {}
    for region, items in by_region.items():
        slugs = listed_slugs(region, listed_dir)
        seen: set[str] = set()
        path = out / f"{region}.csv"
        with open(path, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["symbol", "name", "yahoo", "stockanalysis", "has_listing"])
            for item in sorted(items, key=lambda x: x["symbol"]):
                key = norm_key(item["symbol"])
                if key in seen:
                    continue
                seen.add(key)
                m = resolve(region, item["symbol"], slugs)
                w.writerow([m["symbol"], item["name"], m["yahoo"], m["stockanalysis"],
                            "1" if key in slugs else "0"])
        counts[region] = len(seen)
        log.info("symbols: %s -> %d securities", region, len(seen))
    return counts
