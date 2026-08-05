"""Quarterly top-N portfolio backtest — does the fundamental score actually rank?

Pure fundamentals: NO technicals, no entry timing. Holdings are chosen only by the
point-in-time quality score, so this isolates the question "is the fundamental ranking itself
worth anything?" from every price-based decision.

The per-trade backtest answers "are individual entries good?". This answers a different and
arguably more important question for a positional investor:

    Every quarter, hold the N best-scoring businesses. Sell whatever drops out, buy whatever
    comes in. Equal weight. How does that portfolio do against simply owning the whole market?

Point-in-time throughout: at each rebalance the score is computed from statements at least 90
days old (reporting lag) and nothing about the future is used to pick the holdings. Turnover
and costs are charged on every switch, so the comparison isn't flattered.

Benchmark is an equal-weight buy-and-hold of the same universe over the same window - the
honest question being "did ranking add anything over owning everything?".
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx

from app.core.logging import get_logger
from app.core.safe_path import safe_file
from app.engines.strategy.quality import assess_quality
from app.ingestion.psx_pit_backtest import _fetch_5y, _pit_statements

log = get_logger(__name__)


def psx_portfolio_backtest(
    data_dir: str | Path, top_n: int = 20, rebalance_days: int = 63, warmup: int = 260,
    sample: int = 400, workers: int = 6, cost_bps: float = 30.0, region: str = "psx",
    min_periods: int = 3,
) -> dict[str, Any]:
    out = Path(data_dir)
    rows: list[dict] = json.loads((out / "screener.json").read_text(encoding="utf-8"))
    company = out / "company"

    picks: list[tuple[dict, dict]] = []
    for r in rows:
        if r.get("region") != region or not r.get("provider_symbol"):
            continue
        cf = safe_file(company, f"{r['provider_symbol']}.json")
        if cf is None or not cf.exists():
            continue
        try:
            st = json.loads(cf.read_text(encoding="utf-8")).get("statements") or {}
        except (OSError, json.JSONDecodeError):
            continue
        if len(st.get("income") or []) >= min_periods:
            picks.append((r, st))
        if len(picks) >= sample:
            break

    client = httpx.Client(follow_redirects=True)
    try:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            fetched = list(
                ex.map(lambda p: (p[0], p[1], _fetch_5y(p[0]["provider_symbol"], client)), picks)
            )
    finally:
        client.close()

    # Align every name onto a common date axis so the portfolio can be marked consistently.
    series: dict[str, dict[str, float]] = {}
    statements: dict[str, dict] = {}
    all_dates: set[str] = set()
    for r, st, h in fetched:
        if h is None:
            continue
        dates, _o, _hi, _lo, close, _v = h
        sym = r["provider_symbol"]
        series[sym] = {d: float(c) for d, c in zip(dates, close, strict=False)}
        statements[sym] = st
        all_dates.update(dates)
    if not series:
        return {"error": "no usable price history"}

    axis = sorted(all_dates)
    if len(axis) < warmup + rebalance_days:
        return {"error": "insufficient history"}
    rebal_dates = axis[warmup::rebalance_days]

    cost = cost_bps / 10_000.0
    equity = 1.0                      # strategy portfolio value
    holdings: list[str] = []
    history: list[dict] = []
    turnovers: list[float] = []

    def price(sym: str, day: str) -> float | None:
        return series.get(sym, {}).get(day)

    for i, day in enumerate(rebal_dates[:-1]):
        nxt = rebal_dates[i + 1]

        # Rank by point-in-time quality score.
        scored: list[tuple[float, str]] = []
        for sym, st in statements.items():
            if price(sym, day) is None or price(sym, nxt) is None:
                continue
            q = assess_quality(_pit_statements(st, day))
            if q.eligible and q.score is not None:
                scored.append((q.score, sym))
        scored.sort(reverse=True)
        target = [s for _sc, s in scored[:top_n]]
        if not target:
            history.append({"date": day, "holdings": 0, "period_return_pct": 0.0})
            continue

        # Turnover cost: only the names actually switched are charged.
        changed = len(set(target).symmetric_difference(holdings))
        turnover = changed / max(len(target), 1)
        turnovers.append(turnover)
        equity *= (1 - cost * turnover)

        # Equal-weight return over the holding period.
        rets = []
        for sym in target:
            p0, p1 = price(sym, day), price(sym, nxt)
            if p0 and p1:
                rets.append((p1 - p0) / p0)
        period = sum(rets) / len(rets) if rets else 0.0
        equity *= (1 + period)
        holdings = target
        history.append({
            "date": day, "holdings": len(target),
            "period_return_pct": round(period * 100, 2),
            "equity": round(equity, 4),
        })

    # Benchmark: equal-weight buy-and-hold of every name that existed at the start.
    start, end = axis[warmup], axis[-1]
    bh_rets = []
    for sym in series:
        p0, p1 = price(sym, start), price(sym, end)
        if p0 and p1:
            bh_rets.append((p1 - p0) / p0 * 100.0)
    bh_avg = sum(bh_rets) / len(bh_rets) if bh_rets else None
    bh_med = sorted(bh_rets)[len(bh_rets) // 2] if bh_rets else None

    periods = [h["period_return_pct"] for h in history if "equity" in h]
    wins = [p for p in periods if p > 0]
    result = {
        "market": region,
        "strategy": f"quarterly top-{top_n} by point-in-time quality score, equal weight",
        "window": f"{start} .. {end}",
        "universe": len(series),
        "rebalances": len(periods),
        "total_return_pct": round((equity - 1) * 100, 2),
        "avg_quarter_pct": round(sum(periods) / len(periods), 2) if periods else None,
        "best_quarter_pct": round(max(periods), 2) if periods else None,
        "worst_quarter_pct": round(min(periods), 2) if periods else None,
        "positive_quarters": f"{len(wins)}/{len(periods)}" if periods else None,
        "avg_turnover_pct": round(100 * sum(turnovers) / len(turnovers), 1) if turnovers else None,
        "buy_and_hold_avg_pct": round(bh_avg, 2) if bh_avg is not None else None,
        "buy_and_hold_median_pct": round(bh_med, 2) if bh_med is not None else None,
        "history": history,
        "note": (
            "Point-in-time: holdings are chosen from statements at least 90 days old at each "
            "rebalance. Costs charged on turnover only. Benchmark is equal-weight buy-and-hold "
            "of the same universe over the same window, so the question is whether ranking beat "
            "owning everything."
        ),
    }
    (out / f"{region}_portfolio_backtest.json").write_text(json.dumps(result), encoding="utf-8")
    log.info("portfolio-backtest[%s]: total=%s%% vs BH avg %s%%", region,
             result["total_return_pct"], result["buy_and_hold_avg_pct"])
    return result
