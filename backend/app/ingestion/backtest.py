"""Walk-forward backtest: do the model's signals actually predict forward returns?

The platform shows signals and return-since-signal, but that is self-selected (it only measures
names that already carry a signal today). This measures the real question honestly:

    Rewind to N trading days ago, compute the signal using ONLY the data available then,
    then measure the return actually delivered over the following N days.

No look-ahead: the signal at the cut point is derived from `close[:k]` only. Prices come from
Yahoo chart-v8 (reachable from CI, unlike yfinance fundamentals). Fundamentals are held at
today's value - a known, documented limitation, since we have no point-in-time fundamentals
history; the technical/momentum legs are the ones being tested here.

Output: data/backtest.json - average forward return per signal bucket, plus hit rate.
"""

from __future__ import annotations

import json
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx

from app.core.logging import get_logger
from app.core.safe_path import safe_file
from app.ingestion.tech_refresh import _f, _signal_value_at, fetch_history

log = get_logger(__name__)

BUCKETS = ["strong_buy", "buy", "hold", "sell", "strong_sell"]


def _forward_return(close, k: int) -> float | None:
    """Return delivered from bar k-1 to the last bar, in percent."""
    if k < 1 or k > len(close):
        return None
    start, end = float(close[k - 1]), float(close[-1])
    if start <= 0:
        return None
    return (end - start) / start * 100.0


def backtest(
    data_dir: str | Path, horizon: int = 60, sample: int = 400, workers: int = 8,
    seed: int = 7, only_fundamentals: bool = False, min_price: float = 0.0,
) -> dict[str, Any]:
    """Replay signals `horizon` trading days back over a random sample and score them."""
    out = Path(data_dir)
    rows: list[dict] = json.loads((out / "screener.json").read_text(encoding="utf-8"))
    try:
        regime_map = json.loads(
            (out / "macro_regime.json").read_text(encoding="utf-8")
        ).get("countries", {})
    except (OSError, json.JSONDecodeError):
        regime_map = {}

    # Sample names that actually carry scores, spread across markets.
    pool = [r for r in rows if r.get("provider_symbol") and r.get("technical_score") is not None]
    if only_fundamentals:
        # Restrict to the "real" research universe - names that carry actual financials -
        # instead of the micro-cap tail whose triple-digit swings dominate the raw sample.
        pool = [r for r in pool if r.get("fundamental_score") is not None]
    if min_price:
        pool = [r for r in pool if (_f(r.get("price")) or 0) >= min_price]
    rng = random.Random(seed)
    rng.shuffle(pool)
    picks = pool[:sample]

    company = out / "company"
    client = httpx.Client(follow_redirects=True)
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool_ex:
            hist = list(
                pool_ex.map(lambda r: (r, fetch_history(r["provider_symbol"], client)), picks)
            )
    finally:
        client.close()

    stats: dict[str, dict[str, Any]] = {
        b: {"n": 0, "sum_ret": 0.0, "wins": 0, "rets": []} for b in BUCKETS
    }
    evaluated = 0
    for r, h in hist:
        if h is None:
            continue
        dates, _open, high, low, close, vol = h
        k = len(close) - horizon
        if k < 60:  # need enough history before the cut for the indicators to be valid
            continue

        sc: dict = {}
        cf = safe_file(company, f"{r['provider_symbol']}.json")
        if cf is not None and cf.exists():
            try:
                sc = json.loads(cf.read_text(encoding="utf-8")).get("scores") or {}
            except (OSError, json.JSONDecodeError):
                sc = {}
        legs = (
            _f(sc.get("fundamental")) if sc.get("fundamental") is not None
            else _f(r.get("fundamental_score")),
            _f(sc.get("momentum")), _f(sc.get("quality")), _f(sc.get("risk")),
        )
        sig = _signal_value_at(
            high, low, close, vol, k, legs, regime_map.get(r.get("region")),
            _f(r.get("debt_to_equity")),
        )
        if sig not in stats:
            continue
        ret = _forward_return(close, k)
        if ret is None:
            continue
        stats[sig]["n"] += 1
        stats[sig]["sum_ret"] += ret
        stats[sig]["rets"].append(ret)
        if ret > 0:
            stats[sig]["wins"] += 1
        evaluated += 1

    buckets = {}
    for b in BUCKETS:
        s = stats[b]
        n = s["n"]
        rets = sorted(s["rets"])
        # Median matters here: this universe has thousands of micro-caps whose triple-digit
        # moves can drag a bucket's mean far away from its typical outcome.
        median = rets[n // 2] if n else None
        buckets[b] = {
            "n": n,
            "avg_return_pct": round(s["sum_ret"] / n, 2) if n else None,
            "median_return_pct": round(median, 2) if median is not None else None,
            "hit_rate_pct": round(100.0 * s["wins"] / n, 1) if n else None,
        }

    sb = buckets["strong_buy"]["median_return_pct"]
    ss = buckets["strong_sell"]["median_return_pct"]
    result = {
        "horizon_days": horizon,
        "sample_requested": sample,
        "evaluated": evaluated,
        "buckets": buckets,
        # The headline test: do strong_buy names beat strong_sell names over the horizon?
        "spread_strong_buy_minus_strong_sell": (
            round(sb - ss, 2) if sb is not None and ss is not None else None
        ),
        "note": (
            "Walk-forward: signal computed from data up to the cut only, then the realised "
            "forward return measured. Fundamental/quality/risk legs are held at today's values "
            "(no point-in-time fundamentals), so this primarily validates the technical legs."
        ),
    }
    (out / "backtest.json").write_text(json.dumps(result), encoding="utf-8")
    log.info("backtest: %s", {k: v for k, v in result.items() if k != "note"})
    return result
