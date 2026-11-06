"""Puts a dollar quote on the same basis as a filer's accounts.

THE DEFECT. Everything in the US store is labelled USD, but a foreign filer's statements are in its
own currency and per ordinary share, while the quote is in dollars and per ADS. HDB's rupee earnings
against a dollar price published a P/E of 0.48 and a perfect valuation mark, and its dividend yield
read 47%. About 1,100 listings are exposed, and 346 of them carried a Buy or a Strong Buy.

THE CURE. The Ratios page in our own CSVs states each quarter's true multiples, already converted.
So for a quarter:

    what the accounts say the company is worth = true P/E x net income   (also P/S, P/B)
    factor = that / (dollar close x weighted shares)

The factor carries the exchange rate and the ADS ratio together, so neither has to be known, and it
is the median of the three because any one can be absent. Measured on the first 335 filers it reads
7.18 falling to 6.72 for Atour, which is the dollar against the yuan, and 5.1 to 5.7 for Afya, the
real. Across 726 US companies the median is 0.998, and dollar reporters in Greece, Israel and
Bermuda read 1.00. It is checked, not assumed.

WHO GETS ONE. Every listing not domiciled in the US that has a Ratios page, and a US-domiciled
name only when it is far from 1: the listing calls IH and FINV American, and they read 6.4. Anything
else is left exactly as it was.

The result is stored, not recomputed, because the CSVs live on this machine and CI has only the
store. A name with no entry behaves as it always did.
"""

from __future__ import annotations

import bisect
import csv
import json
import statistics
from collections.abc import Callable
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from app.core.logging import get_logger

log = get_logger(__name__)

BASIS_JSON = Path(__file__).resolve().parents[3] / "data" / "symbols" / "us_reporting_basis.json"
HOME = "United States"
# A US company's factor sits inside this about 94% of the time, on share classes and timing.
NORMAL_BAND = (0.8, 1.25)
_MILLION = 1_000_000.0


class Basis:
    def __init__(self, table: dict[str, dict]) -> None:
        self.table = table
        self._days = {s: sorted(e.get("factors") or {}) for s, e in table.items()}

    def __contains__(self, symbol: object) -> bool:
        return symbol in self.table

    def factor(self, symbol: str, day: str) -> float:
        """Multiplier from the dollar quote to the accounts, on `day`. 1.0 for everyone else.

        The latest quarter at or before the day, or the earliest we hold before that.
        """
        days = self._days.get(symbol)
        if not days:
            return 1.0
        i = bisect.bisect_right(days, day) - 1
        return float(self.table[symbol]["factors"][days[max(i, 0)]])

    def usd_cap(self, symbol: str, price: float | None) -> float | None:
        """Dollar market cap: the listed units at this price. None without a Ratios page."""
        units = (self.table.get(symbol) or {}).get("units")
        if not units or not isinstance(price, int | float) or price <= 0:
            return None
        return round(units * price, 2)

    def on_books(self, symbol: str, price_on: Callable | None) -> Callable | None:
        """`price_on(date)`, in the accounts' terms."""
        if price_on is None or symbol not in self.table:
            return price_on

        def converted(when: str):
            price = price_on(when)
            return price * self.factor(symbol, when) if price else price

        return converted


@lru_cache(maxsize=2)
def load_basis(path: Path = BASIS_JSON) -> Basis:
    try:
        return Basis(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        log.warning("reporting-basis: %s not readable, so no listing is converted", path.name)
        return Basis({})


def _number(text: str | None) -> float | None:
    try:
        return float((text or "").replace(",", "").replace("%", "").strip())
    except ValueError:
        return None


def read_ratios(path: Path) -> tuple[dict[str, dict[str, float | None]], dict[str, float | None]]:
    """A Ratios CSV by period end, plus its Current column.

    The header has come two ways: dates in a "Period Ending" row, or run onto the end of the
    first line after the quarter labels.
    """
    with open(path, encoding="utf-8", newline="") as fh:
        rows = [row for row in csv.reader(fh) if row]
    if not rows:
        return {}, {}
    table = {row[0]: row[1:] for row in rows}
    head = rows[0]
    if "Period Ending" in head:
        at = head.index("Period Ending")
        ends = head[at + 1:at + at]
    else:
        ends = table.get("Period Ending") or []
    wanted = ("PE Ratio", "PS Ratio", "PB Ratio", "Market Capitalization", "Last Close Price")

    def column(j: int) -> dict[str, float | None]:
        return {k: _number((table.get(k) or [])[j]) if j < len(table.get(k) or []) else None
                for k in wanted}

    out: dict[str, dict[str, float | None]] = {}
    current: dict[str, float | None] = {}
    for j, end in enumerate(ends):
        try:
            day = datetime.strptime(end.strip(), "%b %d, %Y").date().isoformat()
        except ValueError:
            continue
        if j == 0 and head[1:2] == ["Current"]:
            current = column(j)
            continue
        out[day] = column(j)
    return out, current


def quarter_factor(ratios: dict[str, float | None], close: float, shares: float,
                   net_income: float | None, revenue: float | None,
                   equity: float | None) -> float | None:
    """Median of what each true multiple implies. None when none of them can be read."""
    quoted = close * shares
    if quoted <= 0:
        return None
    implied = [multiple * base / quoted
               for multiple, base in ((ratios.get("PE Ratio"), net_income),
                                      (ratios.get("PS Ratio"), revenue),
                                      (ratios.get("PB Ratio"), equity))
               if multiple and multiple > 0 and base and base > 0]
    return statistics.median(implied) if implied else None


def entry_for(record: dict, closes: dict[str, float], ratios: dict[str, dict],
              current: dict[str, float | None], country: str | None) -> dict | None:
    """One company's stored entry, or None if it should stay as it is."""
    income, balance = record.get("income") or {}, record.get("balance") or {}

    def at(block: dict, key: str, i: int) -> float | None:
        values = block.get(key) or []
        return values[i] if i < len(values) else None

    days = sorted(closes)
    factors: dict[str, float] = {}
    for i, day in enumerate(record.get("periods") or []):
        row = ratios.get(day)
        shares = at(income, "weighted_shares", i)
        cut = bisect.bisect_right(days, day) - 1
        if not row or not shares or cut < 0 or not closes[days[cut]]:
            continue
        factor = quarter_factor(row, closes[days[cut]], shares, at(income, "net_income", i),
                                at(income, "revenue", i), at(balance, "total_equity", i))
        if factor:
            factors[day] = round(factor, 4)
    if not factors:
        return None
    typical = statistics.median(factors.values())
    if country == HOME and NORMAL_BAND[0] <= typical <= NORMAL_BAND[1]:
        return None
    entry: dict = {"factors": factors}
    cap, close = current.get("Market Capitalization"), current.get("Last Close Price")
    if cap and close:
        entry["units"] = round(cap * _MILLION / close, 1)
    return entry


def build(store: dict[str, dict], pack: dict[str, dict], csv_dir: Path,
          domicile: dict[str, str], previous: dict[str, dict]) -> dict[str, dict]:
    """Every entry the CSVs on this machine can support, over what was already stored."""
    table = dict(previous)
    for path in sorted(csv_dir.glob("*_Ratios.csv")):
        symbol = path.name[:-len("_Ratios.csv")]
        series = pack.get(symbol)
        record = store.get(symbol)
        if not series or not record:
            continue
        closes = dict(zip(series.get("d") or [], series.get("c") or [], strict=False))
        ratios, current = read_ratios(path)
        country = domicile.get(symbol.upper().replace("/", "-"))
        entry = entry_for(record, closes, ratios, current, country)
        if entry:
            table[symbol] = entry
        else:
            table.pop(symbol, None)
    return dict(sorted(table.items()))
