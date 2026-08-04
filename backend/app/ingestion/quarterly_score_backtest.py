"""Does ranking by the fundamental score actually pick better stocks?

Every weighting decision so far has been reasoning. This measures it.

The rule tested is the one being traded: each quarter, buy the top N by fundamental score,
equal weight, hold until the next rebalance.

REBALANCE LAG. A quarter's results are not knowable on the day the quarter ends. Companies
report over the following weeks, so the portfolio is formed TWO MONTHS after the period end -
Dec-25 results are acted on 1 Mar 2026. Without that lag the test buys on information nobody
had, which is the single most common way a backtest invents an edge that does not exist.

BENCHMARK. The primary comparison is the equal-weight return of every scored company in the
market - "the average stock". For an equal-weight portfolio that is the honest benchmark: a
cap-weighted index answers a different question, since beating it may only mean the small names
did well. Where a real index has usable history it is reported alongside.

Point-in-time throughout: the score for a quarter was computed from statements up to that
quarter only, and returns come from our own stored daily bars.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.ingestion.ohlc_store import load_bars

log = get_logger(__name__)

# Yahoo's ^KSE stopped updating in September 2021, so PSX has no usable index here and is
# measured against its own equal-weight universe alone.
INDEX_FOR = {
    "us": "^GSPC",
    "india": "^NSEI",
    "australia": "^AXJO",
    "gcc": "^TASI.SR",
}


def _add_months(when: date, months: int) -> date:
    month = when.month - 1 + months
    year = when.year + month // 12
    month = month % 12 + 1
    day = min(when.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
                         else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)


class Prices:
    """Closes for one market, loaded once and reused across every period."""

    def __init__(self, region: str) -> None:
        self.region = region
        self._cache: dict[str, dict[str, float]] = {}

    def series(self, symbol: str) -> dict[str, float]:
        if symbol not in self._cache:
            bars = load_bars(self.region, symbol)
            out: dict[str, float] = {}
            for day, row in bars.items():
                try:
                    out[day] = float(row[4])
                except (TypeError, ValueError, IndexError):
                    continue
            self._cache[symbol] = out
        return self._cache[symbol]

    def on_or_after(self, symbol: str, when: str) -> tuple[str, float] | None:
        """First close on or after `when` - the first price actually tradeable."""
        series = self.series(symbol)
        days = sorted(d for d in series if d >= when)
        return (days[0], series[days[0]]) if days else None

    def ret(self, symbol: str, start: str, end: str) -> float | None:
        a = self.on_or_after(symbol, start)
        b = self.on_or_after(symbol, end)
        if not a or not b or a[0] >= b[0] or a[1] <= 0:
            return None
        return b[1] / a[1] - 1.0


def _quarters(rows: list[dict]) -> dict[str, dict[str, float]]:
    """{period_end: {symbol: score}} across the market."""
    out: dict[str, dict[str, float]] = {}
    for r in rows:
        symbol = r.get("symbol")
        scores = r.get("score_history") or []
        dates = r.get("score_history_dates") or []
        if not symbol:
            continue
        for score, when in zip(scores, dates):
            if isinstance(score, (int, float)) and when:
                out.setdefault(str(when)[:10], {})[str(symbol)] = float(score)
    return out


def run(data_dir: str | Path, region: str, top_n: int = 20,
        lag_months: int = 2, min_universe: int = 30) -> dict[str, Any]:
    rows = [r for r in json.loads(
        (Path(data_dir) / "screener.json").read_text(encoding="utf-8"))
        if r.get("region") == region and r.get("score_history")]
    if not rows:
        return {"region": region, "error": "no scored history"}

    by_quarter = _quarters(rows)
    prices = Prices(region)
    index_symbol = INDEX_FOR.get(region)
    index_prices = Prices("global") if index_symbol else None

    periods: list[dict[str, Any]] = []
    quarter_ends = sorted(by_quarter)

    for i, quarter_end in enumerate(quarter_ends[:-1]):
        scored = by_quarter[quarter_end]
        if len(scored) < min_universe:
            continue
        try:
            formed = _add_months(date.fromisoformat(quarter_end), lag_months).isoformat()
            exits = _add_months(date.fromisoformat(quarter_ends[i + 1]),
                                lag_months).isoformat()
        except ValueError:
            continue

        ranked = sorted(scored.items(), key=lambda kv: -kv[1])
        picks = [s for s, _ in ranked[:top_n]]

        held = [r for r in (prices.ret(s, formed, exits) for s in picks) if r is not None]
        everyone = [r for r in (prices.ret(s, formed, exits) for s in scored) if r is not None]
        if not held or not everyone:
            continue

        index_ret = None
        if index_symbol and index_prices:
            index_ret = index_prices.ret(index_symbol, formed, exits)

        periods.append({
            "results_for": quarter_end,
            "formed": formed,
            "exited": exits,
            "universe": len(scored),
            "held": len(held),
            "portfolio_pct": round(100 * sum(held) / len(held), 2),
            "equal_weight_pct": round(100 * sum(everyone) / len(everyone), 2),
            "index_pct": None if index_ret is None else round(100 * index_ret, 2),
        })

    if not periods:
        return {"region": region, "error": "no periods with enough data"}

    def compound(key: str) -> float | None:
        total = 1.0
        seen = 0
        for p in periods:
            v = p.get(key)
            if v is not None:
                total *= 1 + v / 100
                seen += 1
        return round(100 * (total - 1), 2) if seen else None

    wins = sum(1 for p in periods
               if p["portfolio_pct"] > p["equal_weight_pct"])
    result = {
        "region": region,
        "top_n": top_n,
        "lag_months": lag_months,
        "periods": len(periods),
        "from": periods[0]["formed"],
        "to": periods[-1]["exited"],
        "portfolio_total_pct": compound("portfolio_pct"),
        "equal_weight_total_pct": compound("equal_weight_pct"),
        "index_total_pct": compound("index_pct"),
        "periods_beating_equal_weight": f"{wins}/{len(periods)}",
        "detail": periods,
    }
    log.info("quarterly-score-backtest[%s]: %s", region,
             {k: v for k, v in result.items() if k != "detail"})
    return result
