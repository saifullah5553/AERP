"""TRUE point-in-time backtest on PSX — the rigorous test the other harnesses couldn't do.

PSX is the one market where we hold dated historical fundamentals: each company carries ~5
TTM statement sets stamped one year apart (2022-03-31 … 2026-03-31), and Yahoo serves ~5 years
of daily prices for the .KA symbols. That combination allows a backtest with NO look-ahead on
either side:

    at each step, the quality gate sees ONLY statements whose fiscal_date <= that day,
    and the entry rules see ONLY bars up to that day.

Because fundamentals now move through time, this is also the first test of the FULL strategy,
including the fundamental exit ("hold while the business stays strong") that earlier harnesses
had to approximate with a stop.

Reported against buy-and-hold over the identical window, so the question is answered plainly:
did the strategy beat simply owning the same companies?
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from app.core.logging import get_logger
from app.engines.strategy.entry import assess_entry
from app.engines.strategy.quality import assess_quality

log = get_logger(__name__)

_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=5y&interval=1d"
_UA = "Mozilla/5.0 (compatible; AERP/1.0)"


def _fetch_5y(sym: str, client: httpx.Client):
    """(dates, open, high, low, close, volume) over ~5 years, or None."""
    try:
        r = client.get(_CHART.format(sym=sym), headers={"User-Agent": _UA}, timeout=25)
        r.raise_for_status()
        res = r.json()["chart"]["result"][0]
        ts = res.get("timestamp") or []
        q = res["indicators"]["quote"][0]
        o, h, low_, c, v = (q.get("open"), q.get("high"), q.get("low"),
                            q.get("close"), q.get("volume"))
        if not c:
            return None
        keep = [i for i in range(len(c)) if c[i] is not None]
        if len(keep) < 400:
            return None
        dates = [datetime.fromtimestamp(ts[i], UTC).date().isoformat() for i in keep]
        arr = lambda src, fb: np.array(  # noqa: E731
            [float(src[i]) if src and src[i] is not None else float(c[i]) for i in keep],
            dtype=float,
        )
        vol = np.array([float(v[i]) if v and v[i] is not None else 0.0 for i in keep])
        return dates, arr(o, c), arr(h, c), arr(low_, c), arr(c, c), vol
    except Exception:  # noqa: BLE001 - one bad symbol shouldn't stop the batch
        return None


def _pit_statements(statements: dict[str, list[dict]], as_of: str) -> dict[str, list[dict]]:
    """Only the statements a person could actually have seen on `as_of`.

    Reports land after the period they describe, so a fiscal date alone would still leak: we
    add a 90-day reporting lag before a period is treated as known.
    """
    cutoff = (datetime.fromisoformat(as_of).date()).toordinal() - 90
    out: dict[str, list[dict]] = {}
    for k, rows in statements.items():
        keep = []
        for r in rows or []:
            fd = str(r.get("fiscal_date") or "")[:10]
            if not fd:
                continue
            try:
                if datetime.fromisoformat(fd).date().toordinal() <= cutoff:
                    keep.append(r)
            except ValueError:
                continue
        out[k] = keep  # already newest-first
    return out


def psx_pit_backtest(
    data_dir: str | Path, sample: int = 250, step: int = 10, warmup: int = 260,
    workers: int = 6, cost_bps: float = 30.0, stop_pct: float = 25.0,
) -> dict[str, Any]:
    out = Path(data_dir)
    rows: list[dict] = json.loads((out / "screener.json").read_text(encoding="utf-8"))
    company = out / "company"

    picks: list[tuple[dict, dict]] = []
    for r in rows:
        if r.get("region") != "psx" or not r.get("provider_symbol"):
            continue
        cf = company / f"{r['provider_symbol']}.json"
        if not cf.exists():
            continue
        try:
            st = json.loads(cf.read_text(encoding="utf-8")).get("statements") or {}
        except (OSError, json.JSONDecodeError):
            continue
        if len(st.get("income") or []) >= 3:
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

    cost = cost_bps / 10_000.0
    trades: list[dict] = []
    bh: list[float] = []
    names = 0
    exit_reasons: dict[str, int] = {}

    for r, st, h in fetched:
        if h is None:
            continue
        dates, _o, high, low, close, vol = h
        n = len(close)
        if n < warmup + 2 * step:
            continue
        names += 1

        in_pos = False
        entry_px = 0.0
        entry_date = ""
        for t in range(warmup, n + 1, step):
            as_of = dates[t - 1]
            px = float(close[t - 1])
            pit = _pit_statements(st, as_of)
            if not (pit.get("income") or []):
                continue
            q = assess_quality(pit)

            if not in_pos:
                if q.eligible:
                    e = assess_entry(high[:t], low[:t], close[:t], vol[:t])
                    if e.triggered:
                        in_pos, entry_px, entry_date = True, px, as_of
            else:
                ret = (px - entry_px) / entry_px
                reason = None
                if not q.eligible:
                    reason = "fundamentals_deteriorated"
                elif ret * 100.0 <= -stop_pct:
                    reason = "stop_loss"
                if reason:
                    trades.append({
                        "symbol": r.get("symbol"), "entry": entry_date, "exit": as_of,
                        "ret_pct": round((ret - 2 * cost) * 100.0, 2), "reason": reason,
                    })
                    exit_reasons[reason] = exit_reasons.get(reason, 0) + 1
                    in_pos = False
        if in_pos:
            ret = (float(close[-1]) - entry_px) / entry_px
            trades.append({
                "symbol": r.get("symbol"), "entry": entry_date, "exit": dates[-1],
                "ret_pct": round((ret - 2 * cost) * 100.0, 2), "reason": "still_open",
            })
            exit_reasons["still_open"] = exit_reasons.get("still_open", 0) + 1

        bh.append((float(close[-1]) - float(close[warmup - 1])) / float(close[warmup - 1]) * 100.0)

    rets = [t["ret_pct"] for t in trades]
    wins = [x for x in rets if x > 0]
    srt = sorted(rets)
    bsrt = sorted(bh)
    result = {
        "market": "psx",
        "point_in_time": True,
        "names_tested": names,
        "window": f"{fetched[0][2][0][warmup - 1]} .. {fetched[0][2][0][-1]}" if fetched and
                  fetched[0][2] else None,
        "trades": len(trades),
        "win_rate_pct": round(100.0 * len(wins) / len(rets), 1) if rets else None,
        "avg_trade_pct": round(sum(rets) / len(rets), 2) if rets else None,
        "median_trade_pct": round(srt[len(srt) // 2], 2) if srt else None,
        "best_pct": round(max(rets), 2) if rets else None,
        "worst_pct": round(min(rets), 2) if rets else None,
        "exit_reasons": exit_reasons,
        "buy_and_hold_avg_pct": round(sum(bh) / len(bh), 2) if bh else None,
        "buy_and_hold_median_pct": round(bsrt[len(bsrt) // 2], 2) if bsrt else None,
        "note": (
            "True point-in-time: the quality gate sees only statements whose fiscal_date is at "
            "least 90 days old at each step (reporting lag), and entries see only prior bars. "
            "Exits are fundamental (gate no longer eligible) or a hard stop. Buy-and-hold is "
            "measured on the same names over the same window."
        ),
    }
    (out / "psx_pit_backtest.json").write_text(json.dumps(result), encoding="utf-8")
    log.info("psx-pit-backtest: %s", {k: v for k, v in result.items() if k != "note"})
    return result
