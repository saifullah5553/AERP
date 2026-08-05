"""Quarterly rebalance ledger — what the top-20 rule actually bought, sold and made.

One row per position: the quarter it entered, the price it was bought at, the price it was sold
at when it dropped out of the top 20, and the return between them. Per market, for the last
four rebalances.

RECONSTRUCTED, NOT A TRADE BLOTTER. The live model portfolio has rebalanced once, so its own
record has 72 entries and no exits - it cannot show four quarters of round trips because four
quarters have not happened yet. This rebuilds them from what we do hold: the score each company
carried at each past quarter-end, and our own stored daily bars. Every price here is a real
close that traded; nothing is modelled. But these are trades the rule WOULD have made, not
trades that were made, and the page says so.

Point-in-time throughout, and the lag is the reason it can claim that. A quarter's results are
not knowable the day the quarter ends - companies report over the following weeks - so a
portfolio formed on Dec-25 results trades on 1 March 2026. Without that lag the ledger buys on
information nobody had, which is the most common way a backtest invents a profit.

Survivorship is the honest caveat: the universe is today's listings, so companies that delisted
are absent, and their absence flatters the record.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.ingestion.quarterly_score_backtest import Prices, _add_months

log = get_logger(__name__)

TOP_N = 20
LAG_MONTHS = 2
QUARTERS = 4
# Below this the "market" is too thin for a top-20 to mean anything - picking 20 of 25 names is
# not a selection, it is the market with a haircut.
MIN_UNIVERSE = 30

REGION_LABELS = {
    "psx": "Pakistan", "us": "US", "india": "India",
    "australia": "Australia", "gcc": "GCC",
}


def _scores_by_quarter(rows: list[dict]) -> dict[str, dict[str, float]]:
    """{quarter_end: {symbol: score}} - the score each name carried AT that quarter end."""
    out: dict[str, dict[str, float]] = {}
    for r in rows:
        symbol = r.get("symbol")
        scores = r.get("score_history") or []
        dates = r.get("score_history_dates") or []
        if not symbol:
            continue
        for score, when in zip(scores, dates, strict=False):
            if isinstance(score, int | float) and when:
                out.setdefault(str(when)[:10], {})[str(symbol)] = float(score)
    return out


def _quarter_label(iso: str) -> str:
    """'Mar 26' for a period end."""
    try:
        year, month = int(iso[:4]), int(iso[5:7])
    except (ValueError, IndexError):
        return iso
    return f"{['Mar', 'Jun', 'Sep', 'Dec'][(month - 1) // 3]} {str(year)[2:]}"


def build_region(rows: list[dict], region: str, prices: Prices,
                 top_n: int = TOP_N, quarters: int = QUARTERS) -> dict[str, Any]:
    """The ledger for one market: the last `quarters` rebalances, with entries and exits."""
    scored = [r for r in rows if r.get("region") == region and r.get("score_history")]
    by_quarter = _scores_by_quarter(scored)
    usable = sorted(q for q, names in by_quarter.items() if len(names) >= MIN_UNIVERSE)
    if len(usable) < 2:
        # Same shape as a full result. A market with no history should render as empty, not
        # crash whatever is reading the file.
        return {"region": region, "label": REGION_LABELS.get(region, region.upper()),
                "top_n": top_n, "lag_months": LAG_MONTHS, "quarters": [],
                "open_positions": [], "realised_trades": 0,
                "realised_avg_return_pct": None, "realised_winners": 0,
                "note": "not enough scored history for a rebalance"}

    # One extra quarter at the front: a position's return needs the rebalance AFTER it, so
    # showing four completed quarters means walking five boundaries.
    walk = usable[-(quarters + 1):]
    names = {r.get("symbol"): r for r in scored}

    held: dict[str, dict] = {}         # symbol -> the open position
    out_quarters: list[dict] = []

    for i, quarter_end in enumerate(walk):
        traded_on = _add_months(date.fromisoformat(quarter_end), LAG_MONTHS).isoformat()
        ranked = sorted(by_quarter[quarter_end].items(), key=lambda kv: -kv[1])
        picks = {s for s, _ in ranked[:top_n]}

        entries, exits = [], []

        # Exits first: a name that was held and is no longer in the top 20 is sold at this
        # rebalance, at this rebalance's price - not at some later "current" price.
        for symbol in list(held):
            if symbol in picks:
                continue
            pos = held.pop(symbol)
            sold = prices.on_or_after(symbol, traded_on)
            exit_px = sold[1] if sold else None
            ret = None
            if exit_px and pos.get("entry_price"):
                ret = round((exit_px / pos["entry_price"] - 1) * 100, 2)
            exits.append({
                "symbol": symbol, "name": (names.get(symbol) or {}).get("name"),
                "sector": (names.get(symbol) or {}).get("sector"),
                "entry_quarter": pos["entry_quarter"], "entry_date": pos["entry_date"],
                "entry_price": pos.get("entry_price"),
                "exit_date": traded_on, "exit_price": exit_px, "return_pct": ret,
                "held_quarters": i - pos["entry_index"],
            })

        for symbol in picks:
            if symbol in held:
                continue
            bought = prices.on_or_after(symbol, traded_on)
            held[symbol] = {
                "entry_quarter": _quarter_label(quarter_end),
                "entry_date": bought[0] if bought else traded_on,
                "entry_price": bought[1] if bought else None,
                "entry_index": i,
            }
            entries.append({
                "symbol": symbol, "name": (names.get(symbol) or {}).get("name"),
                "sector": (names.get(symbol) or {}).get("sector"),
                "score": round(by_quarter[quarter_end][symbol], 2),
                "entry_date": held[symbol]["entry_date"],
                "entry_price": held[symbol]["entry_price"],
            })

        closed = [e["return_pct"] for e in exits if e["return_pct"] is not None]
        out_quarters.append({
            "results_for": quarter_end,
            "quarter": _quarter_label(quarter_end),
            "traded_on": traded_on,
            "universe": len(by_quarter[quarter_end]),
            "entries": sorted(entries, key=lambda e: -(e["score"] or 0)),
            "exits": sorted(exits, key=lambda e: (e["return_pct"] is None,
                                                  -(e["return_pct"] or 0))),
            "closed_avg_return_pct": round(sum(closed) / len(closed), 2) if closed else None,
            "closed_winners": sum(1 for r in closed if r > 0),
            "closed_count": len(closed),
        })

    # Whatever is still held at the end is an OPEN position, marked to the newest close. Shown
    # separately from realised returns, because an unrealised gain is not a result.
    open_rows = []
    for symbol, pos in held.items():
        series = prices.series(symbol)
        last = max(series) if series else None
        px = series.get(last) if last else None
        ret = None
        if px and pos.get("entry_price"):
            ret = round((px / pos["entry_price"] - 1) * 100, 2)
        open_rows.append({
            "symbol": symbol, "name": (names.get(symbol) or {}).get("name"),
            "sector": (names.get(symbol) or {}).get("sector"),
            "entry_quarter": pos["entry_quarter"], "entry_date": pos["entry_date"],
            "entry_price": pos.get("entry_price"), "last_price": px,
            "return_pct": ret, "open": True,
        })

    realised = [e["return_pct"] for q in out_quarters for e in q["exits"]
                if e["return_pct"] is not None]
    return {
        "region": region,
        "label": REGION_LABELS.get(region, region.upper()),
        "top_n": top_n,
        "lag_months": LAG_MONTHS,
        # The first walked quarter only opens positions; it has no prior quarter to close, so
        # it is not one of the four the page reports on.
        "quarters": out_quarters[1:] if len(out_quarters) > 1 else out_quarters,
        "open_positions": sorted(open_rows, key=lambda r: -(r["return_pct"] or -999)),
        "realised_trades": len(realised),
        "realised_avg_return_pct": (round(sum(realised) / len(realised), 2)
                                    if realised else None),
        "realised_winners": sum(1 for r in realised if r > 0),
    }


def build(data_dir: str | Path, top_n: int = TOP_N,
          quarters: int = QUARTERS) -> dict[str, Any]:
    out = Path(data_dir)
    rows = json.loads((out / "screener.json").read_text(encoding="utf-8"))
    regions = [r for r in REGION_LABELS if any(x.get("region") == r for x in rows)]
    ledger = {}
    for region in regions:
        prices = Prices(region)
        ledger[region] = build_region(rows, region, prices, top_n, quarters)
    doc = {"markets": ledger, "top_n": top_n, "lag_months": LAG_MONTHS,
           "reconstructed": True}
    (out / "rebalance_ledger.json").write_text(json.dumps(doc), encoding="utf-8")
    summary = {r: {"quarters": len(v["quarters"]), "trades": v["realised_trades"],
                   "avg": v["realised_avg_return_pct"]} for r, v in ledger.items()}
    log.info("rebalance-ledger: %s", summary)
    return summary
