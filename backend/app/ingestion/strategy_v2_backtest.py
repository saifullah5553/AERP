"""Backtest the quality-gate + price-action strategy against buy-and-hold.

Rule under test (the methodology this platform is being rebuilt around):

    enter  when a quality-gated business first triggers a price-action entry
    hold   while the business stays fundamentally strong - no churning on oscillators
    exit   when the fundamental gate fails, or a hard stop is hit

Point-in-time handling, stated plainly: price/volume are strictly historical (every entry
decision uses bars[:t] only), but the STATEMENTS are today's - we have no point-in-time
fundamentals. So this measures the ENTRY TIMING component honestly while holding business
quality fixed. It answers "among businesses that are strong today, does buying them as they
start moving beat simply holding them?" - which is exactly the question the redesign hinges on.
"""

from __future__ import annotations

import json
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx

from app.core.logging import get_logger
from app.engines.strategy.entry import assess_entry
from app.engines.strategy.quality import assess_quality
from app.ingestion.tech_refresh import _f, fetch_history

log = get_logger(__name__)


def _median(xs: list[float]) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    return s[len(s) // 2]


def strategy_v2_backtest(
    data_dir: str | Path, sample: int = 500, step: int = 5, warmup: int = 200,
    workers: int = 8, seed: int = 17, cost_bps: float = 20.0, stop_pct: float = 25.0,
) -> dict[str, Any]:
    out = Path(data_dir)
    rows: list[dict] = json.loads((out / "screener.json").read_text(encoding="utf-8"))
    company = out / "company"

    pool = [
        r for r in rows
        if r.get("provider_symbol") and (_f(r.get("price")) or 0) >= 1.0
    ]
    rng = random.Random(seed)
    rng.shuffle(pool)

    # Only names we hold statements for - the gate is meaningless without them.
    picks: list[tuple[dict, dict]] = []
    for r in pool:
        cf = company / f"{r['provider_symbol']}.json"
        if not cf.exists():
            continue
        try:
            st = json.loads(cf.read_text(encoding="utf-8")).get("statements") or {}
        except (OSError, json.JSONDecodeError):
            continue
        if st.get("income"):
            picks.append((r, st))
        if len(picks) >= sample:
            break

    client = httpx.Client(follow_redirects=True)
    try:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            fetched = list(
                ex.map(lambda p: (p[0], p[1], fetch_history(p[0]["provider_symbol"], client)),
                       picks)
            )
    finally:
        client.close()

    cost = cost_bps / 10_000.0
    trades: list[float] = []
    bh: list[float] = []
    gated_out = 0
    names = 0

    for _r, st, h in fetched:
        if h is None:
            continue
        _dates, _open, high, low, close, vol = h
        n = len(close)
        if n < warmup + 2 * step:
            continue

        # Quality gate (fixed - today's statements; see module docstring).
        q = assess_quality(st)
        if not q.passed:
            gated_out += 1
            continue
        names += 1

        in_pos = False
        entry_px = 0.0
        for t in range(warmup, n + 1, step):
            px = float(close[t - 1])
            if not in_pos:
                e = assess_entry(high[:t], low[:t], close[:t], vol[:t])
                if e.triggered:
                    in_pos, entry_px = True, px
            else:
                # Hold while strong; only a hard stop closes the position, because the
                # fundamental exit can't trigger with fixed statements.
                if (px - entry_px) / entry_px * 100.0 <= -stop_pct:
                    trades.append(((px - entry_px) / entry_px - 2 * cost) * 100.0)
                    in_pos = False
        if in_pos:
            trades.append(((float(close[-1]) - entry_px) / entry_px - 2 * cost) * 100.0)

        bh.append((float(close[-1]) - float(close[warmup - 1])) / float(close[warmup - 1]) * 100.0)

    wins = [t for t in trades if t > 0]
    result = {
        "rule": f"quality gate + price-action entry, hold while strong (stop -{stop_pct:.0f}%)",
        "quality_names": names,
        "gated_out": gated_out,
        "trades": len(trades),
        "win_rate_pct": round(100.0 * len(wins) / len(trades), 1) if trades else None,
        "avg_trade_pct": round(sum(trades) / len(trades), 2) if trades else None,
        "median_trade_pct": round(_median(trades), 2) if trades else None,
        "best_trade_pct": round(max(trades), 2) if trades else None,
        "worst_trade_pct": round(min(trades), 2) if trades else None,
        "buy_and_hold_avg_pct": round(sum(bh) / len(bh), 2) if bh else None,
        "buy_and_hold_median_pct": round(_median(bh), 2) if bh else None,
        "note": (
            "Entry timing is point-in-time (bars[:t] only). Statements are today's - no "
            "point-in-time fundamentals - so business quality is held fixed and the exit is a "
            "hard stop rather than fundamental deterioration. Buy-and-hold is measured on the "
            "same quality-gated names over the same window, so the comparison is like for like."
        ),
    }
    (out / "strategy_v2_backtest.json").write_text(json.dumps(result), encoding="utf-8")
    log.info("strategy-v2-backtest: %s", {k: v for k, v in result.items() if k != "note"})
    return result
