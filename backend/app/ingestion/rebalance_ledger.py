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
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.ingestion.model_portfolio import SIZE_BY_REGION
from app.ingestion.quarterly_score_backtest import Prices, _add_months

log = get_logger(__name__)

TOP_N = 20
LAG_MONTHS = 2
QUARTERS = 0        # 0 = every quarter we have scores for, back to 2021
# Below this the "market" is too thin for a top-20 to mean anything - picking 20 of 25 names is
# not a selection, it is the market with a haircut.
MIN_UNIVERSE = 30
# The same gate the model portfolio applies, and for the same reason: a quarter only becomes a
# rebalance once most of the market has reported it. Ranking is a comparison, so a handful of
# early filers judged on June against everyone else on March rewards whoever reported first
# rather than whoever is better. Both pages must agree about when a rebalance happened or the
# history will not describe the portfolio it claims to.
MIN_COVERAGE = 0.70

REGION_LABELS = {
    "psx": "Pakistan", "us": "US", "india": "India",
    "australia": "Australia", "gcc": "GCC",
}


def _calendar_quarter_end(iso: str) -> str | None:
    """The CALENDAR quarter a period end falls in: 2026-05-31 -> 2026-06-30.

    Companies do not share a fiscal calendar. Left on their raw period ends, US names produced
    125 distinct "rebalance dates" - one per fiscal year-end in the market - so the ledger was
    rebalancing on dates no portfolio could act on and ranking companies that had reported
    months apart against each other. Bucketing to calendar quarters is what the screener's
    Jun-26 column already does.
    """
    try:
        year, month = int(iso[:4]), int(iso[5:7])
    except (ValueError, IndexError):
        return None
    if not 1 <= month <= 12:
        return None
    end_month = ((month - 1) // 3 + 1) * 3
    return f"{year:04d}-{end_month:02d}-{ {3: 31, 6: 30, 9: 30, 12: 31}[end_month] }"


def _scores_by_quarter(rows: list[dict]) -> dict[str, dict[str, float]]:
    """{calendar quarter end: {symbol: score}} - the score each name carried at that rebalance.

    Where a company reports twice inside one calendar quarter the later print wins: it is the
    figure that would have been known when the rebalance happened.
    """
    out: dict[str, dict[str, tuple[str, float]]] = {}
    for r in rows:
        symbol = r.get("symbol")
        scores = r.get("score_history") or []
        dates = r.get("score_history_dates") or []
        if not symbol:
            continue
        for score, when in zip(scores, dates, strict=False):
            if not (isinstance(score, int | float) and when):
                continue
            bucket = _calendar_quarter_end(str(when)[:10])
            if not bucket:
                continue
            slot = out.setdefault(bucket, {})
            prior = slot.get(str(symbol))
            if prior is None or str(when)[:10] >= prior[0]:
                slot[str(symbol)] = (str(when)[:10], float(score))
    return {q: {sym: val for sym, (_, val) in names.items()} for q, names in out.items()}


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

    # Trim the NEWEST quarters until one is properly reported. The coverage question only
    # applies at the front: an old quarter is thin because we hold less history that far back,
    # not because companies had not filed, and gating on that deleted India's entire record.
    # At the front it is the live question the portfolio also asks - on 5 August only 11% of
    # PSX had filed Jun-26, and a rebalance there would rank those against everyone else's
    # March figures.
    fullest = max((len(names) for names in by_quarter.values()), default=0)
    while usable and fullest and len(by_quarter[usable[-1]]) < MIN_COVERAGE * fullest:
        usable.pop()
    if len(usable) < 2:
        # Same shape as a full result. A market with no history should render as empty, not
        # crash whatever is reading the file.
        return {"region": region, "label": REGION_LABELS.get(region, region.upper()),
                "top_n": top_n, "lag_months": LAG_MONTHS, "quarters": [],
                "open_positions": [], "realised_trades": 0,
                "realised_avg_return_pct": None, "realised_winners": 0,
                "note": "not enough scored history for a rebalance"}

    # One extra quarter at the front: a position's return needs the rebalance AFTER it, so
    # showing N completed quarters means walking N+1 boundaries. quarters=0 walks the lot -
    # the score history runs twenty periods, so the record reaches back to 2021 rather than
    # stopping at whatever the last four happen to be.
    walk = usable if not quarters else usable[-(quarters + 1):]
    names = {r.get("symbol"): r for r in scored}

    held: dict[str, dict] = {}         # symbol -> the open position
    out_quarters: list[dict] = []

    today = datetime.now(UTC).date().isoformat()
    for i, quarter_end in enumerate(walk):
        # The calendar target. Two months after the quarter end lands on a weekend or a holiday
        # about a third of the time - 12 of 39 rebalances did, and 2026-05-31 is a Sunday. It
        # is only ever the date we START looking from; every fill below resolves to a session
        # that actually traded, and `traded_on` is restated to one further down.
        target = _add_months(date.fromisoformat(quarter_end), LAG_MONTHS).isoformat()
        traded_on = target
        # A rebalance two months after a quarter that has not finished reporting cannot have
        # happened. US names with an August fiscal year-end bucket into Sep-26, whose trade
        # date is in November - showing it as a quarter with no holdings and no return reads
        # as missing data rather than as the future.
        if traded_on > today:
            continue
        # A name with no price history cannot be bought, held or marked - IMS sat in the PSX
        # portfolio with no entry price, no current price and a blank return, occupying a slot
        # the rule would have given to the next scorer. The live portfolio already required a
        # price to rank; the reconstruction has to require one too, or the two select from
        # different universes.
        ranked = [kv for kv in sorted(by_quarter[quarter_end].items(), key=lambda kv: -kv[1])
                  if prices.series(kv[0])]
        picks = {s for s, _ in ranked[:top_n]}

        entries, exits = [], []

        # Exits first: a name that was held and is no longer in the top 20 is sold at this
        # rebalance, at this rebalance's price - not at some later "current" price.
        # Snapshot before any changes: these are the names the quarter was actually held in.
        held_at_start = list(held)
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
                # The session it actually sold on, not the calendar target. The price came from
                # that session; dating it two days earlier described a fill nobody could have got.
                "exit_date": sold[0] if sold else traded_on,
                "exit_price": exit_px, "return_pct": ret,
                "held_quarters": i - pos["entry_index"],
            })

        for symbol in picks:
            if symbol in held:
                continue
            bought = prices.on_or_after(symbol, traded_on)
            held[symbol] = {
                "entry_quarter": _quarter_label(quarter_end),
                # The period end whose results BOUGHT this position. Carried explicitly rather
                # than re-derived later from the company's newest filing: a holding entered on
                # Mar-26 results does not start trading on Jun-26 results merely because June
                # has since been published. That substitution put results dated 2026-06-30 on
                # positions bought 2026-06-01 - a purchase made on figures that did not exist
                # for another month.
                "entry_results_for": quarter_end,
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

        # Restate the quarter's trade date to a session the market was actually open on: the
        # earliest date anything in this rebalance filled. The target is only a starting point,
        # and a ledger row reading "traded on Sunday 31 May" is not a record of a trade.
        # Only dates that came from a real price lookup. A name with no history falls back to
        # the target itself, and since the target is the earliest possible date, letting those
        # into the min() put the weekend straight back - which is why four PSX quarters still
        # said Saturday after the first attempt.
        sessions = [d for d in ([e["entry_date"] for e in entries]
                                + [x["exit_date"] for x in exits]) if d and d != target]
        if sessions:
            traded_on = min(sessions)

        # The PORTFOLIO's return for the quarter just ended: every name held through it,
        # equal weight, priced from this rebalance back to the last one. Not the average of
        # what happened to be SOLD - a name held four quarters dumps its whole multi-quarter
        # gain into the bucket it exits, and compounding those gave PSX +3,531%, which is not a
        # quarterly return series, it is the same profits counted several times over.
        period_returns: list[float] = []
        if i > 0:
            prev_traded = out_quarters[-1]["traded_on"] if out_quarters else None
            if prev_traded:
                for symbol in held_at_start:
                    ret = prices.ret(symbol, prev_traded, traded_on)
                    if ret is not None:
                        period_returns.append(ret * 100)

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
            # What the portfolio itself did over the quarter - the number worth compounding.
            "portfolio_return_pct": (round(sum(period_returns) / len(period_returns), 2)
                                     if period_returns else None),
            "held_through": len(period_returns),
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
            "entry_results_for": pos.get("entry_results_for"),
            "entry_price": pos.get("entry_price"), "last_price": px,
            "return_pct": ret, "open": True,
        })

    realised = [e["return_pct"] for q in out_quarters for e in q["exits"]
                if e["return_pct"] is not None]
    # Compounded quarter on quarter, equal-weight within each - what the rule would have
    # returned held continuously, rather than an average of unrelated trades.
    compounded = 1.0
    for q in out_quarters[1:]:
        if q["portfolio_return_pct"] is not None:
            compounded *= 1 + q["portfolio_return_pct"] / 100
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
        "compounded_return_pct": round((compounded - 1) * 100, 2) if len(out_quarters) > 1
        else None,
        "first_quarter": out_quarters[1]["quarter"] if len(out_quarters) > 1 else None,
        "last_quarter": out_quarters[-1]["quarter"] if out_quarters else None,
    }


def build(data_dir: str | Path, top_n: int = TOP_N,
          quarters: int = QUARTERS) -> dict[str, Any]:
    out = Path(data_dir)
    rows = json.loads((out / "screener.json").read_text(encoding="utf-8"))
    regions = [r for r in REGION_LABELS if any(x.get("region") == r for x in rows)]
    ledger = {}
    for region in regions:
        prices = Prices(region)
        # The SAME size the live portfolio holds for this market. Reconstructing a top-20 US
        # history while the portfolio ran top-15 described a rule nobody was following, and was
        # one of three reasons the two pages could not agree on a single holding.
        size = SIZE_BY_REGION.get(region, top_n)
        ledger[region] = build_region(rows, region, prices, size, quarters)
    doc = {"markets": ledger, "top_n": top_n, "lag_months": LAG_MONTHS,
           "reconstructed": True}
    (out / "rebalance_ledger.json").write_text(json.dumps(doc), encoding="utf-8")
    summary = {r: {"quarters": len(v["quarters"]), "trades": v["realised_trades"],
                   "avg": v["realised_avg_return_pct"]} for r, v in ledger.items()}
    log.info("rebalance-ledger: %s", summary)
    return summary
