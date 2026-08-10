"""Factor-level backtest: which individual metrics actually predict forward returns?

The composite blends ~12 technical metrics with hand-picked weights. This measures each one
on its own, so weights can be based on evidence instead of intuition:

    At a cut point N trading days back, compute every metric from data available THEN, rank
    the universe by it, and compare the forward return of the top quintile vs the bottom.

Two statistics per factor:
  * `spread_pct`  - median forward return of the top quintile minus the bottom quintile.
                    Positive means "high values of this metric led to better returns".
  * `ic`          - Spearman rank correlation between the metric and forward return
                    (-1..1). This is the standard "information coefficient"; |IC| > ~0.03
                    across a large sample is considered meaningful in practice.

Strictly point-in-time: every metric is derived from `close[:k]`, never from data after the
cut. Purely technical factors are used because those are the ones we can reconstruct
historically - we have no point-in-time fundamentals.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx

from app.core.logging import get_logger
from app.engines.price_action.engine import analyse as analyse_price_action
from app.ingestion.tech_refresh import _f, fetch_history

log = get_logger(__name__)


def _rank(values: list[float]) -> list[float]:
    """Average ranks (1-based), ties share the mean rank."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float | None:
    """Rank correlation; None when there isn't enough variation to be meaningful."""
    n = len(xs)
    if n < 20:
        return None
    rx, ry = _rank(xs), _rank(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=False))
    dx = sum((a - mx) ** 2 for a in rx)
    dy = sum((b - my) ** 2 for b in ry)
    if dx <= 0 or dy <= 0:
        return None
    return num / (dx * dy) ** 0.5


def _median(xs: list[float]) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    return s[len(s) // 2]


def factor_backtest(
    data_dir: str | Path, horizon: int = 60, sample: int = 800, workers: int = 8,
    seed: int = 11, only_fundamentals: bool = False, min_price: float = 1.0,
) -> dict[str, Any]:
    out = Path(data_dir)
    rows: list[dict] = json.loads((out / "screener.json").read_text(encoding="utf-8"))

    pool = [r for r in rows if r.get("provider_symbol") and r.get("technical_score") is not None]
    if only_fundamentals:
        pool = [r for r in pool if r.get("fundamental_score") is not None]
    if min_price:
        pool = [r for r in pool if (_f(r.get("price")) or 0) >= min_price]

    import random

    rng = random.Random(seed)
    rng.shuffle(pool)
    picks = pool[:sample]

    client = httpx.Client(follow_redirects=True)
    try:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            fetched = list(ex.map(lambda r: fetch_history(r["provider_symbol"], client), picks))
    finally:
        client.close()

    # observations[factor] = [(metric_value, forward_return), ...]
    observations: dict[str, list[tuple[float, float]]] = {}
    used = 0
    for h in fetched:
        if h is None:
            continue
        dates, open_, high, low, close, vol = h
        k = len(close) - horizon
        if k < 60:
            continue
        start, end = float(close[k - 1]), float(close[-1])
        if start <= 0:
            continue
        fwd = (end - start) / start * 100.0
        # Point-in-time: the price-action read from the pre-cut window only.
        #
        # This backtest existed to measure whether each INDICATOR predicted forward returns,
        # and its answer was that they did not - momentum scored an IC of -0.094, every
        # technical input a negative predictor over sixty days. Those inputs are gone, so it
        # now measures the components that replaced them. The question is the same and it is
        # still worth asking of the new engine rather than assuming an improvement.
        read = analyse_price_action(dates[:k], open_[:k], high[:k], low[:k], close[:k], vol[:k])
        metrics = dict(read.components)
        metrics["technical_score"] = read.score
        metrics["relative_volume"] = read.volume.get("relative")
        for name, val in metrics.items():
            v = _f(val)
            if v is not None:
                observations.setdefault(name, []).append((v, fwd))
        used += 1

    factors: dict[str, Any] = {}
    for name, obs in sorted(observations.items()):
        if len(obs) < 40:
            continue
        obs_sorted = sorted(obs, key=lambda t: t[0])
        q = max(1, len(obs_sorted) // 5)
        bottom = [r for _v, r in obs_sorted[:q]]
        top = [r for _v, r in obs_sorted[-q:]]
        mt, mb = _median(top), _median(bottom)
        ic = spearman([v for v, _r in obs], [r for _v, r in obs])
        factors[name] = {
            "n": len(obs),
            "top_quintile_median_pct": round(mt, 2) if mt is not None else None,
            "bottom_quintile_median_pct": round(mb, 2) if mb is not None else None,
            "spread_pct": round(mt - mb, 2) if mt is not None and mb is not None else None,
            "ic": round(ic, 4) if ic is not None else None,
        }

    ranked = sorted(
        (f for f in factors.items() if f[1]["ic"] is not None),
        key=lambda kv: abs(kv[1]["ic"]), reverse=True,
    )
    result = {
        "horizon_days": horizon,
        "names_evaluated": used,
        "universe": "fundamentals-only" if only_fundamentals else "all",
        "factors": factors,
        "strongest_by_abs_ic": [k for k, _v in ranked[:5]],
        "note": (
            "Point-in-time: every metric is computed from data before the cut only. "
            "spread_pct = top-quintile median forward return minus bottom-quintile. "
            "ic = Spearman rank correlation with forward return; |ic| > ~0.03 over a large "
            "sample is considered meaningful. A NEGATIVE value means high readings of that "
            "metric preceded WORSE returns - i.e. the engine should not reward it."
        ),
    }
    (out / "factor_backtest.json").write_text(json.dumps(result), encoding="utf-8")
    log.info("factor-backtest: evaluated=%d factors=%d", used, len(factors))
    return result
