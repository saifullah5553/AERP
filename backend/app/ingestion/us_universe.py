"""Which US listings the US model portfolio may hold.

WHY THE US NEEDS THIS AND THE OTHER MARKETS DO NOT. The universe here is everything listed in New
York, which is not the same as American companies, and it runs from Apple down to shells worth a
few million. Ranked on score alone, the top 15 averaged a median cap near $1bn and a quarter of it
was foreign listings.

Foreign listings are the worse half of that. HDB files in rupees and trades in dollars, and our
statements carry the rupees labelled USD, so it published a P/E of 0.48 and a perfect valuation
mark. PDD, BSBR and IBN are the same. Until each filer's reporting currency is known, their
valuation cannot be trusted, so a US portfolio holds US-domiciled companies.

THE RULE, measured September 2021 to mid-2026 on repaired prices, 18 quarters:

    S&P 500 (cap-weighted)                   +68.9%
    every US company over $2bn, equal weight +23.1%
    the rule before this                     +11.5%
    this rule                                +70.2%

So most of the gap to the index was never stock selection: the S&P beat the average large US share
by 46 points on a handful of giants. The rule beats equal weight by about 2 points a quarter, at
t=1.5, which is suggestive and not proof. Survivorship flatters every line but the index.

The ledger, with the P/E and closed-end fund checks added, reads +78.9% against +69.7% over 20
quarters, but +12.1% against +27.1% from December 2024. The lead was built before that: the book
holds almost no technology, and the index has been led by it.

Domicile is listing data, not fundamentals. It comes from the exchange's public screener and is
kept in data/symbols/us_domicile.csv. A name missing from that file is not eligible: we cannot say
its accounts are in dollars. If the file is absent the filter is off, with a warning, because an
empty portfolio would be a worse answer than an unfiltered one.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Callable, Container, Iterable
from datetime import date
from pathlib import Path

import httpx

from app.core.logging import get_logger

log = get_logger(__name__)

DOMICILE_CSV = Path(__file__).resolve().parents[3] / "data" / "symbols" / "us_domicile.csv"
LISTINGS_URL = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=10000&download=true"
HOME = "United States"
# Below this a position cannot be built or left without moving the price, and the equal-weight
# universe of smaller names returned less than the larger one in every test.
MIN_MARKET_CAP = 2_000_000_000.0
# Under three times earnings is almost never a real price. It is a filer the listing calls American
# whose accounts are not in dollars (Tencent Music, at 1.45) or earnings that will not repeat, and
# either way the score is reading a number nobody should pay for.
MIN_CREDIBLE_PE = 3.0
# How far down the ranking to qualify names. The sector limit has to be able to walk past a run of
# financials, but it never needs the whole market, and each name costs a page read.
SCAN_DEPTH = 400


def _key(symbol: str) -> str:
    return str(symbol).upper().replace("/", "-")


def load_domicile(path: Path = DOMICILE_CSV) -> dict[str, str]:
    """Symbol to country of domicile, or {} when the file has not been built."""
    if not path.exists():
        log.warning("us-universe: %s missing, so the domicile filter is off", path.name)
        return {}
    with open(path, encoding="utf-8", newline="") as fh:
        return {_key(row["symbol"]): row["country"] for row in csv.DictReader(fh)}


def _cap(listing: dict) -> float:
    try:
        return float(listing.get("marketCap") or 0)
    except ValueError:
        return 0.0


def refresh_domicile(path: Path = DOMICILE_CSV) -> int:
    """Rewrite the file from the exchange's listing. Keeps the old file if the fetch fails."""
    resp = httpx.get(LISTINGS_URL, timeout=60, headers={
        "User-Agent": "Mozilla/5.0 (compatible; AERP/1.0)", "Accept": "application/json"})
    resp.raise_for_status()
    rows = resp.json()["data"]["rows"]
    # No market cap in the listing means a closed-end fund, not an operating company: UTG, DNP and
    # EVT were ranking as asset managers. Blank country keeps them out.
    table = {_key(r["symbol"]): (r.get("country") or "").strip() if _cap(r) else ""
             for r in rows if r.get("symbol")}
    if len(table) < 3000:
        raise ValueError(f"listing looks truncated: {len(table)} symbols")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        out = csv.writer(fh, lineterminator="\n")
        out.writerow(["symbol", "country"])
        out.writerows(sorted(table.items()))
    return len(table)


class Investable:
    """Answers, for one quarter's rebalance, whether a name could have been bought then.

    Reads a company's page only when the ranking reaches it, and only once.
    """

    def __init__(self, company: Path, provider: dict[str, str], domicile: dict[str, str],
                 price_on: Callable[[str, str], tuple[str, float] | None],
                 off_basis: Container[str] = ()) -> None:
        self.company = company
        self.provider = provider
        self.domicile = domicile
        self.price_on = price_on
        self.off_basis = off_basis
        self._income: dict[str, dict[str, dict]] = {}

    def _rows(self, symbol: str) -> dict[str, dict]:
        """Income rows by calendar quarter end, later filings winning a shared quarter."""
        if symbol not in self._income:
            from app.ingestion.rebalance_ledger import _calendar_quarter_end

            rows: dict[str, dict] = {}
            try:
                doc = json.loads((self.company / f"{self.provider.get(symbol, symbol)}.json")
                                 .read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                doc = {}
            income = (doc.get("statements_ttm") or {}).get("income") or []
            for row in reversed(income):
                quarter = _calendar_quarter_end(str(row.get("fiscal_date") or "")[:10])
                if quarter:
                    rows[quarter] = row
            self._income[symbol] = rows
        return self._income[symbol]

    def __call__(self, symbol: str, quarter_end: str, trade_day: str) -> bool:
        if self.domicile and self.domicile.get(_key(symbol)) != HOME:
            return False
        # Listed as American, but its accounts do not agree with a dollar price: IH, FINV, TME.
        if symbol in self.off_basis:
            return False
        row = self._rows(symbol).get(quarter_end)
        if not row:
            return False
        income, shares = row.get("net_income"), row.get("weighted_shares")
        if not isinstance(income, int | float) or income <= 0:
            return False
        if not isinstance(shares, int | float) or shares <= 0:
            return False
        filled = self.price_on(symbol, trade_day)
        if not filled or (date.fromisoformat(filled[0]) - date.fromisoformat(trade_day)).days > 10:
            return False
        cap = filled[1] * shares
        return cap >= MIN_MARKET_CAP and cap / income >= MIN_CREDIBLE_PE


def qualified(ranked: Iterable[tuple[str, float]], quarter_end: str, trade_day: str,
              check: Investable) -> list[tuple[str, float]]:
    """The ranking with everything uninvestable taken out, in order, to SCAN_DEPTH names."""
    out: list[tuple[str, float]] = []
    for item in ranked:
        if check(item[0], quarter_end, trade_day):
            out.append(item)
            if len(out) == SCAN_DEPTH:
                break
    return out
