"""Daily all-market technical → composite → signal recompute (Yahoo chart-v8 history).

The free CI refresh can't run yfinance (429), so non-PSX scores were frozen between local
rebuilds. But chart-v8 returns full daily HISTORY from CI, and the technical scorer is a pure
function — so we can recompute the technical leg daily, reblend the composite with the
committed fundamental/momentum/quality/risk scores + the macro-regime overlay, re-derive the
signal, and patch the snapshot (screener.json + company/*.json). Also feeds movers.json so
upgrades/downgrades appear across all markets. PSX is handled by the main pipeline.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from app.core.logging import get_logger
from app.core.safe_path import safe_file
from app.engines.composite.dimensions import momentum_score
from app.engines.composite.engine import WEIGHTS
from app.engines.composite.regime_modifier import apply_regime_modifier
from app.engines.composite.signals import derive_signal
from app.engines.patterns.engine import detect_all
from app.engines.strategy.signal import evaluate as strategy_evaluate
from app.engines.technical.engine import _scoring_metrics
from app.engines.technical.indicators import compute_indicators
from app.engines.technical.scoring import score_technical

log = get_logger(__name__)

_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1y&interval=1d"
_UA = "Mozilla/5.0 (compatible; AERP/1.0)"
MIN_BARS = 60


def _f(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def fetch_history(sym: str, client: httpx.Client):
    """chart-v8 daily OHLCV → (dates, open, high, low, close, volume), or None.

    `dates` are ISO strings aligned with the arrays (for signal-inception backtesting).
    `open` is carried so candlestick patterns can be detected from the same fetch."""
    try:
        resp = client.get(_CHART.format(sym=sym), headers={"User-Agent": _UA}, timeout=20)
        resp.raise_for_status()
        res = resp.json()["chart"]["result"][0]
        ts = res.get("timestamp") or []
        q = res["indicators"]["quote"][0]
        opens = q.get("open")
        highs, lows, closes, vols = q.get("high"), q.get("low"), q.get("close"), q.get("volume")
        if not closes:
            return None
        bars = [
            (highs[i], lows[i], closes[i], vols[i] if vols else None,
             ts[i] if i < len(ts) else None, opens[i] if opens else None)
            for i in range(len(closes))
            if closes[i] is not None
        ]
        if len(bars) < MIN_BARS:
            return None
        close = np.array([b[2] for b in bars], dtype=float)
        high = np.array([b[0] if b[0] is not None else b[2] for b in bars], dtype=float)
        low = np.array([b[1] if b[1] is not None else b[2] for b in bars], dtype=float)
        vol = np.array([b[3] if b[3] is not None else 0.0 for b in bars], dtype=float)
        open_ = np.array([b[5] if b[5] is not None else b[2] for b in bars], dtype=float)
        dates = [
            datetime.fromtimestamp(b[4], UTC).date().isoformat() if b[4] else "" for b in bars
        ]
        return dates, open_, high, low, close, vol
    except Exception:  # noqa: BLE001 - one bad symbol shouldn't stop the batch
        return None


def _reblend(fund, tech, mom, qual, risk) -> tuple[float | None, float, dict]:
    comps = {"fundamental": fund, "technical": tech, "momentum": mom, "quality": qual, "risk": risk}
    present = {k: v for k, v in comps.items() if v is not None}
    anchor = comps["fundamental"] is not None or comps["technical"] is not None
    if not present or not anchor:
        return None, 0.0, {}
    total_w = sum(WEIGHTS[k] for k in present)
    base = round(sum(v * WEIGHTS[k] for k, v in present.items()) / total_w, 2)
    return base, round(total_w, 4), present


def _composite_at(high, low, close, vol, k, legs, regime, de):
    """Recomputed (composite, coverage, present) using only the first k bars, or None."""
    ind = compute_indicators(high[:k], low[:k], close[:k], vol[:k])
    tech = score_technical(_scoring_metrics(ind)).score
    if tech is None:
        return None
    fund, mom, qual, risk = legs
    base, cov, present = _reblend(fund, _f(tech), mom, qual, risk)
    if base is None:
        return None
    comp, _ = apply_regime_modifier(base, regime, de)
    return comp, cov, present


def _signal_value_at(high, low, close, vol, k, legs, regime, de, comp_offset=0.0) -> str | None:
    """The derived signal value using only the first k bars (for inception backtesting).

    ``comp_offset`` is a constant added to the recomputed composite so the series can be
    calibrated to a committed score (see ``_backtest_psx``): our close-only EOD history
    scores the technical leg a little differently than the live pipeline (which also folds
    in today's real OHLC bar), so we anchor the recompute to the shown score and let the
    real price trajectory decide only *when* the signal changed.
    """
    c = _composite_at(high, low, close, vol, k, legs, regime, de)
    if c is None:
        return None
    comp, cov, present = c
    return derive_signal(comp + comp_offset, cov, present).signal.value


def _signal_since(dates, high, low, close, vol, legs, regime, de, current,
                  lookback=250, comp_offset=0.0):
    """Walk back over history to the earliest day the current signal has held → (date, close).
    Real inception, not fabricated — capped at `lookback` trading days."""
    n = len(close)
    floor = max(MIN_BARS - 1, n - 1 - lookback)
    inception = floor
    for j in range(n - 1, floor - 1, -1):
        s = _signal_value_at(high, low, close, vol, j + 1, legs, regime, de, comp_offset)
        if s != current:  # includes None → treat as boundary
            inception = j + 1
            break
        inception = j
    idx = max(0, min(inception, n - 1))
    d = dates[idx] if idx < len(dates) and dates[idx] else None
    return d, float(close[idx])


# Browser-like headers for the PSX portal (it's picky about the default httpx UA).
_PSX_HDRS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120 Safari/537.36"
    ),
    "Referer": "https://dps.psx.com.pk/",
    "Accept": "application/json, text/plain, */*",
}


def _fetch_psx_history(sym: str):
    """PSX portal EOD history → (dates, close, volume) for the last ~300 bars, or None."""
    from app.ingestion.psx_market import parse_eod

    try:
        resp = httpx.get(
            f"https://dps.psx.com.pk/timeseries/eod/{sym}", headers=_PSX_HDRS, timeout=20
        )
        resp.raise_for_status()
        bars = parse_eod(resp.text)
    except Exception:  # noqa: BLE001 - one bad symbol shouldn't stop the batch
        return None
    if not bars or len(bars) < MIN_BARS:
        return None
    bars = bars[-300:]
    close = np.array([float(b.close) for b in bars], dtype=float)
    vol = np.array([float(b.volume or 0) for b in bars], dtype=float)
    dates = [b.date.date().isoformat() for b in bars]
    return dates, close, vol


def _backtest_psx(rows, company, regime_map, today, limit):
    """Backfill signal_since / return-since for PSX from portal EOD history, keeping the
    DB-computed composite/signal (we only DATE the shown signal, using the same raw scale)."""
    psx_rows = [r for r in rows if r.get("region") == "psx" and r.get("provider_symbol")]
    if limit is not None:
        psx_rows = psx_rows[:limit]
    if not psx_rows:
        return
    syms = [r.get("symbol") or r["provider_symbol"].replace(".KA", "") for r in psx_rows]
    hist: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        for r, h in zip(psx_rows, pool.map(_fetch_psx_history, syms), strict=False):
            if h is not None:
                hist[r["provider_symbol"]] = h
    regime = regime_map.get("psx")
    updated = 0
    for r in psx_rows:
        h = hist.get(r["provider_symbol"])
        committed = r.get("signal")
        if not h or not committed:
            continue
        dates, close, vol = h
        sc: dict = {}
        cf = safe_file(company, f"{r['provider_symbol']}.json")
        if cf is None:
            continue
        if cf.exists():
            try:
                sc = json.loads(cf.read_text(encoding="utf-8")).get("scores") or {}
            except (OSError, json.JSONDecodeError):
                sc = {}
        fund = _f(sc.get("fundamental"))
        if fund is None:
            fund = _f(r.get("fundamental_score"))
        legs = (fund, _f(sc.get("momentum")), _f(sc.get("quality")), _f(sc.get("risk")))
        de = _f(r.get("debt_to_equity"))

        # Anchor the EOD recompute to the committed composite: our close-only history scores
        # the technical leg a touch differently than the live pipeline, so instead of
        # rejecting every small mismatch we shift the whole recomputed series by a constant
        # so "today" reproduces the shown score, then let the real price trajectory decide
        # WHEN the signal last changed. Skip only when even the anchored signal can't match
        # the shown one (coverage/legs genuinely diverged) or the shift is implausibly large.
        cur = _composite_at(close, close, close, vol, len(close), legs, regime, de)
        committed_comp = _f(r.get("composite_score"))
        if cur is None or committed_comp is None:
            continue
        offset = committed_comp - cur[0]
        if abs(offset) > 40:
            continue
        anchored = _signal_value_at(
            close, close, close, vol, len(close), legs, regime, de, offset
        )
        if anchored != committed:
            continue
        since, price_at = _signal_since(
            dates, close, close, close, vol, legs, regime, de, committed, comp_offset=offset
        )
        cur_price = _f(r.get("price")) or float(close[-1])
        ret = round((cur_price - price_at) / price_at * 100.0, 2) if price_at else None
        r["signal_since"] = since or today
        r["price_at_signal"] = round(price_at, 4) if price_at else None
        r["signal_return_pct"] = ret
        if cf.exists():
            try:
                d = json.loads(cf.read_text(encoding="utf-8"))
                if isinstance(d.get("signal"), dict):
                    d["signal"]["signal_since"] = r["signal_since"]
                    d["signal"]["price_at_signal"] = r["price_at_signal"]
                    d["signal"]["signal_return_pct"] = ret
                cf.write_text(json.dumps(d), encoding="utf-8")
            except (OSError, json.JSONDecodeError):
                pass
        updated += 1
    log.info("PSX signal-since backtest: %d updated", updated)


def refresh_technicals(
    data_dir: str | Path,
    skip_regions: tuple[str, ...] = ("psx",),
    workers: int = 8,
    limit: int | None = None,
) -> dict[str, int]:
    out = Path(data_dir)
    rows: list[dict] = json.loads((out / "screener.json").read_text(encoding="utf-8"))
    try:
        _reg = json.loads((out / "macro_regime.json").read_text(encoding="utf-8"))
        regime_map = _reg.get("countries", {})
    except (OSError, json.JSONDecodeError):
        regime_map = {}

    targets = [r for r in rows if r.get("region") not in skip_regions and r.get("provider_symbol")]
    if limit is not None:
        targets = targets[:limit]

    syms = [r["provider_symbol"] for r in targets]
    hist: dict[str, Any] = {}
    client = httpx.Client(follow_redirects=True)
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = pool.map(lambda s: fetch_history(s, client), syms)
            for sym, h in zip(syms, results, strict=False):
                if h is not None:
                    hist[sym] = h
    finally:
        client.close()

    company = out / "company"
    today = datetime.now(UTC).date().isoformat()
    updated = 0
    deltas: dict[str, dict] = {}
    smoves: dict[str, dict] = {}  # strong-buy crossings (time-to-buy / time-to-sell)

    for r in targets:
        sym = r["provider_symbol"]
        h = hist.get(sym)
        if h is None:
            continue
        dates, open_, high, low, close, vol = h
        ind = compute_indicators(high, low, close, vol)
        tech = score_technical(_scoring_metrics(ind)).score
        if tech is None:
            continue
        # Committed non-technical legs + statements from the company file (fall back to the
        # screener row for the scores).
        sc: dict = {}
        statements: dict = {}
        cf = safe_file(company, f"{sym}.json")
        if cf is None:
            continue
        if cf.exists():
            try:
                _cdoc = json.loads(cf.read_text(encoding="utf-8"))
                sc = _cdoc.get("scores") or {}
                statements = _cdoc.get("statements") or {}
            except (OSError, json.JSONDecodeError):
                sc, statements = {}, {}

        # ── Strategy engine: quality gate → price-action entry → hold-while-strong ──
        # Reuses this same OHLC fetch, so it costs no extra network.
        strategy: dict | None = None
        try:
            strategy = strategy_evaluate(statements, high, low, close, vol).as_dict()
        except Exception:  # noqa: BLE001 - the strategy must never break the refresh
            strategy = None
        if strategy:
            r["strategy_action"] = strategy["action"]
            r["strategy_conviction"] = strategy["conviction"]
            r["quality_passed"] = strategy["quality_passed"]
            r["quality_score"] = strategy["quality_score"]
            r["entry_score"] = strategy["entry_score"]
        fund = _f(sc.get("fundamental"))
        if fund is None:
            fund = _f(r.get("fundamental_score"))
        mom, qual, risk = _f(sc.get("momentum")), _f(sc.get("quality")), _f(sc.get("risk"))
        # Momentum is purely price-derived, so recompute it here from the fresh indicators —
        # this also fills the leg for expanded names the DB pipeline never scored.
        fresh_mom, _mbd = momentum_score(ind)
        if fresh_mom is not None:
            mom = _f(fresh_mom)
        regime = regime_map.get(r.get("region"))
        de = _f(r.get("debt_to_equity"))
        if fund is None and mom is None and qual is None and risk is None:
            # Technical-only name: shrink toward neutral so a raw technical score can't
            # masquerade as a full composite (keeps the expanded tail from flooding the top).
            composite = round(50.0 + (tech - 50.0) * WEIGHTS["technical"], 2)
            coverage, present = WEIGHTS["technical"], {"technical": tech}
        else:
            base, coverage, present = _reblend(fund, _f(tech), mom, qual, risk)
            if base is None:
                continue
            composite, _bd = apply_regime_modifier(base, regime, de)
        sig = derive_signal(composite, coverage, present)

        # Backtest the real signal-inception date + return-since (fixes "all show today").
        legs = (fund, _f(sc.get("momentum")), _f(sc.get("quality")), _f(sc.get("risk")))
        since, price_at = _signal_since(
            dates, high, low, close, vol, legs, regime, de, sig.signal.value
        )
        cur_price = _f(r.get("price")) or float(close[-1])
        ret = round((cur_price - price_at) / price_at * 100.0, 2) if price_at else None

        # Candlestick / chart / harmonic patterns from the same daily OHLC fetch. The DB
        # pipeline only detects these for the markets it ingests (PSX in CI), so doing it
        # here keeps patterns fresh across the whole universe every day.
        pat_rows: list[dict] = []
        try:
            today_d = dates[-1] if dates else today
            for hit in detect_all(open_, high, low, close):
                sidx = hit.start_index
                pat_rows.append({
                    "timeframe": "1d", "detected_on": today_d,
                    "name": hit.name, "category": hit.category.value,
                    "direction": hit.direction.value,
                    "confidence": round(float(hit.confidence), 4), "is_active": True,
                    "start_date": dates[sidx] if sidx is not None and sidx < len(dates) else None,
                    "breakout_level": hit.breakout_level,
                    "target_price": hit.target_price, "stop_level": hit.stop_level,
                })
        except Exception:  # noqa: BLE001 - pattern detection must never break the refresh
            pat_rows = []
        if pat_rows:
            best = max(pat_rows, key=lambda p: p["confidence"])
            cand = [p for p in pat_rows if p["category"] == "candlestick"]
            chrt = [p for p in pat_rows if p["category"] == "chart"]
            r["top_candlestick"] = (
                max(cand, key=lambda p: p["confidence"])["name"] if cand else None
            )
            r["top_chart_pattern"] = (
                max(chrt, key=lambda p: p["confidence"])["name"] if chrt else None
            )
            r["top_pattern"] = best["name"]

        old = r.get("composite_score")
        old_sig = r.get("signal")
        new_sig = sig.signal.value
        _record_signal_move(smoves, r, old_sig, new_sig, sig.label, composite, cur_price, today)
        r["technical_score"] = round(tech, 2)
        r["composite_score"] = composite
        r["signal"] = new_sig
        r["signal_label"] = sig.label
        r["signal_since"] = since or today
        r["price_at_signal"] = round(price_at, 4) if price_at else None
        r["signal_return_pct"] = ret

        if old is not None and abs(composite - old) >= 1.0:
            deltas[sym] = {
                "provider_symbol": sym, "symbol": r.get("symbol"), "name": r.get("name"),
                "region": r.get("region"), "composite": composite, "prev": old,
                "delta": round(composite - old, 2), "fundamental": r.get("fundamental_score"),
                "technical": round(tech, 2), "date": today,
            }

        if cf.exists():
            try:
                d = json.loads(cf.read_text(encoding="utf-8"))
                if isinstance(d.get("scores"), dict):
                    d["scores"]["technical"] = round(tech, 2)
                    if mom is not None:
                        d["scores"]["momentum"] = round(mom, 2)
                if pat_rows:
                    d["patterns"] = pat_rows
                if strategy:
                    d["strategy"] = strategy
                    d["scores"]["composite"] = composite
                if isinstance(d.get("signal"), dict):
                    d["signal"]["signal_type"] = sig.signal.value
                    d["signal"]["label"] = sig.label
                    d["signal"]["signal_since"] = r["signal_since"]
                    d["signal"]["price_at_signal"] = r["price_at_signal"]
                    d["signal"]["signal_return_pct"] = ret
                cf.write_text(json.dumps(d), encoding="utf-8")
            except (OSError, json.JSONDecodeError):
                pass
        updated += 1

    # ── PSX signal-inception backtest (portal EOD history — raw scale, matches PSX prices) ──
    if "psx" in skip_regions:
        _backtest_psx(rows, out / "company", regime_map, today, limit)

    (out / "screener.json").write_text(json.dumps(rows), encoding="utf-8")
    _update_movers(out, deltas, today)
    _update_signal_moves(out, smoves, today)

    result = {
        "targets": len(targets), "quoted": len(hist),
        "updated": updated, "movers": len(deltas), "signal_moves": len(smoves),
    }
    log.info("refresh-technicals: %s", result)
    return result


_EXIT_HYSTERESIS = 77.0  # strong_buy band is >=80; require a clear drop below it to call an exit


def _record_signal_move(
    dst: dict[str, dict], r: dict, old_sig, new_sig, label, composite, price, today: str
) -> None:
    """Record actionable signal transitions. **Strong Buy is the only buy zone.**

    * BUY  (time to buy) = the name entered **strong_buy**.
    * EXIT (time to sell/trim) = the name **left strong_buy** (to buy, hold, sell or lower).

    Exit uses hysteresis (composite must fall clearly below 80, i.e. <=77) so a name wobbling
    right on the 80-point boundary between refreshes — composite drifting 80.1→79.9 — doesn't
    spam exit alerts. Recorded with direction "sell" (the frontend labels it EXIT). Ignores
    first-observation (no prior signal).
    """
    if not old_sig or not new_sig or old_sig == new_sig:
        return
    c = _f(composite)
    if new_sig == "strong_buy":
        direction = "buy"  # old != new (checked above) → genuinely entered the buy zone
    elif old_sig == "strong_buy":
        if c is not None and c > _EXIT_HYSTERESIS:
            return
        direction = "sell"
    else:
        return
    dst[r.get("provider_symbol")] = {
        "provider_symbol": r.get("provider_symbol"), "symbol": r.get("symbol"),
        "name": r.get("name"), "region": r.get("region"),
        "direction": direction, "from": old_sig, "to": new_sig, "label": label,
        "composite": composite, "price": price, "date": today,
        # The fundamental quality score alongside the composite. A buy/sell page that shows
        # only the composite cannot say whether a crossing came from a good business or a
        # chart, and that is the distinction the whole gate exists to draw.
        "quality": r.get("quality_score"), "quality_grade": r.get("quality_grade"),
    }


_MAX_MOVES_PER_RUN = 10  # more crossings than this in one run = a score-recompute batch, not real


def _update_signal_moves(out: Path, moves: dict[str, dict], today: str) -> None:
    """Rolling 30-day feed of strong-buy crossings (buy/exit timing alerts)."""
    # A genuine trading day flips only a handful of names across the Strong-Buy line. A big
    # batch means the composite was re-baselined (formula/fundamentals rebuild), so every
    # prior-vs-new diff fires on the same run date — a misleading cluster, not real events.
    # Drop the whole batch rather than stamp dozens of fake same-day transitions.
    if len(moves) > _MAX_MOVES_PER_RUN:
        log.info(
            "signal-moves: %d crossings in one run (> %d) — treating as a recompute batch, "
            "not recording", len(moves), _MAX_MOVES_PER_RUN
        )
        moves = {}
    path = out / "signal_moves.json"
    recent: dict[str, dict] = {}
    if path.exists():
        try:
            for m in json.loads(path.read_text(encoding="utf-8")).get("all", []):
                recent[m.get("provider_symbol")] = m
        except (OSError, json.JSONDecodeError):
            pass
    cutoff = (datetime.now(UTC).date() - timedelta(days=30)).isoformat()
    recent = {k: v for k, v in recent.items() if (v.get("date") or "") >= cutoff}
    recent.update(moves)
    allm = sorted(recent.values(), key=lambda m: (m.get("date") or ""), reverse=True)
    path.write_text(json.dumps({
        "generated_at": datetime.now(UTC).isoformat(),
        "buy": [m for m in allm if m.get("direction") == "buy"],
        "sell": [m for m in allm if m.get("direction") == "sell"],
        "all": allm,
    }), encoding="utf-8")


def _update_movers(out: Path, deltas: dict[str, dict], today: str) -> None:
    path = out / "movers.json"
    recent: dict[str, dict] = {}
    if path.exists():
        try:
            for m in json.loads(path.read_text(encoding="utf-8")).get("all", []):
                recent[m.get("provider_symbol")] = m
        except (OSError, json.JSONDecodeError):
            pass
    cutoff = (datetime.now(UTC).date() - timedelta(days=7)).isoformat()
    recent = {k: v for k, v in recent.items() if (v.get("date") or "") >= cutoff}
    recent.update(deltas)
    allm = sorted(recent.values(), key=lambda m: (m.get("date") or ""), reverse=True)
    path.write_text(json.dumps({
        "generated_at": datetime.now(UTC).isoformat(),
        "upgrades": sorted([m for m in allm if m["delta"] > 0], key=lambda m: -m["delta"]),
        "downgrades": sorted([m for m in allm if m["delta"] < 0], key=lambda m: m["delta"]),
        "all": allm,
    }), encoding="utf-8")
