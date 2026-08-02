"""Simulate the actual trading rule: buy when a name ENTERS strong_buy, sell when it LEAVES.

This is the decisive test for that strategy. Rather than bucketing signals, it walks forward
through history one step at a time, recomputing the signal from only the data available at
each step, and executes the rule:

    flat  + signal becomes strong_buy  -> BUY at that bar's close
    long  + signal stops being strong_buy -> SELL at that bar's close

Every trade's realised return is recorded, then compared against simply buying and holding the
same names over the same period. If the rule has an edge, it must beat buy-and-hold; if it
doesn't, the rule is costing money versus doing nothing.

No look-ahead: signals at step t use close[:t] only. Fundamental/quality/risk legs are held at
today's values (we have no point-in-time fundamentals) - a documented limitation that mainly
affects the fundamental leg, not the entry/exit timing being tested here.

Costs: `cost_bps` is charged on entry and exit so results aren't flattered by ignoring
spread/commission.
"""

from __future__ import annotations

import json
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx

from app.core.logging import get_logger
from app.ingestion.tech_refresh import _f, _signal_value_at, fetch_history

log = get_logger(__name__)


def _median(xs: list[float]) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    return s[len(s) // 2]


def strategy_backtest(
    data_dir: str | Path, sample: int = 500, step: int = 5, warmup: int = 120,
    workers: int = 8, seed: int = 13, only_fundamentals: bool = True,
    min_price: float = 1.0, cost_bps: float = 20.0,
) -> dict[str, Any]:
    out = Path(data_dir)
    rows: list[dict] = json.loads((out / "screener.json").read_text(encoding="utf-8"))
    try:
        regime_map = json.loads(
            (out / "macro_regime.json").read_text(encoding="utf-8")
        ).get("countries", {})
    except (OSError, json.JSONDecodeError):
        regime_map = {}

    pool = [r for r in rows if r.get("provider_symbol") and r.get("technical_score") is not None]
    if only_fundamentals:
        pool = [r for r in pool if r.get("fundamental_score") is not None]
    if min_price:
        pool = [r for r in pool if (_f(r.get("price")) or 0) >= min_price]
    rng = random.Random(seed)
    rng.shuffle(pool)
    picks = pool[:sample]

    client = httpx.Client(follow_redirects=True)
    try:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            fetched = list(
                ex.map(lambda r: (r, fetch_history(r["provider_symbol"], client)), picks)
            )
    finally:
        client.close()

    company = out / "company"
    cost = cost_bps / 10_000.0
    trades: list[dict] = []
    bh_returns: list[float] = []
    names_tested = 0

    for r, h in fetched:
        if h is None:
            continue
        _dates, _open, high, low, close, vol = h
        n = len(close)
        if n < warmup + 2 * step:
            continue

        sc: dict = {}
        cf = company / f"{r['provider_symbol']}.json"
        if cf.exists():
            try:
                sc = json.loads(cf.read_text(encoding="utf-8")).get("scores") or {}
            except (OSError, json.JSONDecodeError):
                sc = {}
        fund = _f(sc.get("fundamental"))
        if fund is None:
            fund = _f(r.get("fundamental_score"))
        legs = (fund, _f(sc.get("momentum")), _f(sc.get("quality")), _f(sc.get("risk")))
        regime = regime_map.get(r.get("region"))
        de = _f(r.get("debt_to_equity"))

        in_pos = False
        entry_px = 0.0
        for t in range(warmup, n + 1, step):
            sig = _signal_value_at(high, low, close, vol, t, legs, regime, de)
            px = float(close[t - 1])
            if not in_pos and sig == "strong_buy":
                in_pos, entry_px = True, px
            elif in_pos and sig != "strong_buy":
                gross = (px - entry_px) / entry_px
                trades.append({
                    "symbol": r.get("symbol"),
                    "ret_pct": round((gross - 2 * cost) * 100.0, 3),
                })
                in_pos = False
        if in_pos:  # mark any open position to the last close
            gross = (float(close[-1]) - entry_px) / entry_px
            trades.append({
                "symbol": r.get("symbol"),
                "ret_pct": round((gross - 2 * cost) * 100.0, 3),
                "open": True,
            })

        # Benchmark: hold the same name across the identical window.
        bh_returns.append((float(close[-1]) - float(close[warmup - 1])) / float(close[warmup - 1])
                          * 100.0)
        names_tested += 1

    rets = [t["ret_pct"] for t in trades]
    wins = [x for x in rets if x > 0]
    avg = sum(rets) / len(rets) if rets else None
    bh_avg = sum(bh_returns) / len(bh_returns) if bh_returns else None
    bh_med = _median(bh_returns)

    result = {
        "rule": "buy when signal enters strong_buy; sell when it leaves strong_buy",
        "names_tested": names_tested,
        "step_days": step,
        "cost_bps_per_side": cost_bps,
        "trades": len(trades),
        "win_rate_pct": round(100.0 * len(wins) / len(rets), 1) if rets else None,
        "avg_trade_pct": round(avg, 2) if avg is not None else None,
        "median_trade_pct": round(_median(rets), 2) if rets else None,
        "best_trade_pct": round(max(rets), 2) if rets else None,
        "worst_trade_pct": round(min(rets), 2) if rets else None,
        "buy_and_hold_avg_pct": round(bh_avg, 2) if bh_avg is not None else None,
        "buy_and_hold_median_pct": round(bh_med, 2) if bh_med is not None else None,
        "note": (
            "Signals recomputed from close[:t] only (no look-ahead). Costs charged both sides. "
            "Compare avg_trade_pct against buy_and_hold: the rule must beat simply holding, "
            "otherwise it is destroying value versus doing nothing. Single ~1y window - "
            "momentum/mean-reversion is regime dependent, so re-run across regimes before "
            "drawing conclusions."
        ),
    }
    (out / "strategy_backtest.json").write_text(json.dumps(result), encoding="utf-8")
    log.info("strategy-backtest: %s", {k: v for k, v in result.items() if k != "note"})
    return result
