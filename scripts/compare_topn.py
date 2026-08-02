"""Compare top-N portfolio sizes on one price fetch per market.

Running the backtest three times would re-download five years of history three times, so this
fetches once per market and replays the same data for N = 10 / 15 / 20.

IMPORTANT: picking whichever N looks best here is data mining. With only ~10 quarters of
history the gaps between sizes are usually inside the noise, and the "winner" often flips on a
different window. Treat this as a sanity check on concentration, not as an optimisation.

Run from backend/:  python ../scripts/compare_topn.py
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

sys.path.insert(0, ".")  # run from backend/
from app.engines.strategy.quality import assess_quality  # noqa: E402
from app.ingestion.psx_pit_backtest import _fetch_5y, _pit_statements  # noqa: E402

OUT = Path("../frontend/public/data")
COST = 30.0 / 10_000.0
REBAL = 63


def load(region: str, sample: int, min_periods: int = 3):
    rows = json.loads((OUT / "screener.json").read_text(encoding="utf-8"))
    cdir = OUT / "company"
    picks = []
    for r in rows:
        if r.get("region") != region or not r.get("provider_symbol"):
            continue
        cf = cdir / f"{r['provider_symbol']}.json"
        if not cf.exists():
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
        with ThreadPoolExecutor(max_workers=6) as ex:
            fetched = list(
                ex.map(lambda p: (p[0], p[1], _fetch_5y(p[0]["provider_symbol"], client)), picks)
            )
    finally:
        client.close()

    series, statements, all_dates = {}, {}, set()
    for r, st, h in fetched:
        if h is None:
            continue
        dates, _o, _hi, _lo, close, _v = h
        sym = r["provider_symbol"]
        series[sym] = dict(zip(dates, (float(c) for c in close), strict=False))
        statements[sym] = st
        all_dates.update(dates)
    return series, statements, sorted(all_dates)


def simulate(series, statements, axis, top_n: int, warmup: int):
    rebal = axis[warmup::REBAL]
    equity, holdings, periods, turns = 1.0, [], [], []
    for i, day in enumerate(rebal[:-1]):
        nxt = rebal[i + 1]
        scored = []
        for sym, st in statements.items():
            if series.get(sym, {}).get(day) is None or series.get(sym, {}).get(nxt) is None:
                continue
            q = assess_quality(_pit_statements(st, day))
            if q.eligible and q.score is not None:
                scored.append((q.score, sym))
        scored.sort(reverse=True)
        target = [s for _sc, s in scored[:top_n]]
        if not target:
            continue
        turn = len(set(target).symmetric_difference(holdings)) / max(len(target), 1)
        turns.append(turn)
        equity *= (1 - COST * turn)
        rets = [
            (series[s][nxt] - series[s][day]) / series[s][day]
            for s in target if series.get(s, {}).get(day) and series.get(s, {}).get(nxt)
        ]
        period = sum(rets) / len(rets) if rets else 0.0
        equity *= (1 + period)
        periods.append(period * 100)
        holdings = target
    wins = [p for p in periods if p > 0]
    return {
        "top_n": top_n,
        "total_pct": round((equity - 1) * 100, 2),
        "avg_qtr_pct": round(sum(periods) / len(periods), 2) if periods else None,
        "worst_qtr_pct": round(min(periods), 2) if periods else None,
        "best_qtr_pct": round(max(periods), 2) if periods else None,
        "positive": f"{len(wins)}/{len(periods)}",
        "turnover_pct": round(100 * sum(turns) / len(turns), 1) if turns else None,
    }


def benchmark(series, axis, warmup: int):
    start, end = axis[warmup], axis[-1]
    rets = [
        (series[s][end] - series[s][start]) / series[s][start] * 100
        for s in series if series[s].get(start) and series[s].get(end)
    ]
    rets.sort()
    return {
        "bh_avg_pct": round(sum(rets) / len(rets), 2) if rets else None,
        "bh_median_pct": round(rets[len(rets) // 2], 2) if rets else None,
    }


def main() -> int:
    for region, warmup, sample in (("psx", 512, 400), ("australia", 575, 400)):
        series, statements, axis = load(region, sample)
        if not series:
            print(f"{region}: no data")
            continue
        bh = benchmark(series, axis, warmup)
        print(f"\n=== {region.upper()} | window {axis[warmup]} .. {axis[-1]} "
              f"| universe {len(series)} ===")
        print(f"{'N':>4} {'total%':>9} {'avg qtr':>9} {'worst':>8} {'best':>8} "
              f"{'positive':>9} {'turnover':>9}")
        results = []
        for n in (10, 15, 20):
            r = simulate(series, statements, axis, n, warmup)
            results.append(r)
            print(f"{r['top_n']:>4} {r['total_pct']:>9} {r['avg_qtr_pct']:>9} "
                  f"{r['worst_qtr_pct']:>8} {r['best_qtr_pct']:>8} "
                  f"{r['positive']:>9} {r['turnover_pct']:>9}")
        print(f"  benchmark: equal-weight BH {bh['bh_avg_pct']}% avg "
              f"| median stock {bh['bh_median_pct']}%")
        (OUT / f"{region}_topn_comparison.json").write_text(
            json.dumps({"window": f"{axis[warmup]} .. {axis[-1]}", "universe": len(series),
                        "results": results, **bh}), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
