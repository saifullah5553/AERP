"""Daily all-market technical → composite → signal recompute (Yahoo chart-v8 history).

The free CI refresh can't run yfinance (429), so non-PSX scores were frozen between local
rebuilds. But chart-v8 returns full daily HISTORY from CI, and the technical scorer is a pure
function — so we can recompute the technical leg daily, reblend the composite with the
committed fundamental/momentum/quality/risk scores + the macro-regime overlay, re-derive the
signal, and patch the snapshot (screener.json + company/*.json). Also feeds movers.json so
upgrades/downgrades appear across all markets.

PSX GOES THROUGH THE SAME PASS. This file used to skip it on the grounds that "the main pipeline"
handled it, and the main pipeline had not produced a PSX score since a local run on 10 Aug 2026:
all 445 technical scores and signals were carried forward unchanged for three months, on the
retired indicator engine, with no price-action read at all. LUCK showed 82.34 against 53 from
its real chart, and 275 of 445 signals contradicted their own composite. See
`_on_exchange_closes` for the only way PSX differs.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from app.core.logging import get_logger
from app.core.safe_path import safe_file
from app.engines.composite.engine import WEIGHTS
from app.engines.composite.regime_modifier import apply_regime_modifier
from app.engines.composite.signals import derive_signal
from app.engines.patterns.engine import detect_all
from app.engines.price_action.engine import analyse as analyse_price_action
from app.engines.strategy.signal import evaluate as strategy_evaluate

log = get_logger(__name__)

_CHART = "https://{host}.finance.yahoo.com/v8/finance/chart/{sym}?range=1y&interval=1d"
_UA = "Mozilla/5.0 (compatible; AERP/1.0)"
MIN_BARS = 60
# PSX candles come from Yahoo but the exchange's closes decide whether to believe them.
PSX_BAR_TOLERANCE = 0.01   # same tolerance as the daily reconciliation in psx_bars
PSX_MAX_LAG_DAYS = 5       # a weekend and a holiday; beyond that Yahoo has stopped carrying it
PSX_MAX_GAP = 0.25         # two sessions at the exchange's 10% limit, with room
PSX_VOLUME_WINDOW = 20
# A read this recent outlives a failed fetch. Yahoo refuses some requests on any large pass: HUBC
# and AVN had a chart on one run and none on the next, and that is not a reason to blank them.
PSX_KEEP_READ_DAYS = 7
# Raise this whenever the scoring itself changes. A score from an older engine is not comparable
# with a new one, so the first read under a new version is a re-baseline and records no mover.
TECHNICAL_ENGINE = 2
RETRY_PAUSE_SECONDS = 20
RETRY_WORKERS = 2
WHY_SAMPLE = 3
# Everything a technical read writes onto a row, and so what must go when there is no read.
_READ_FIELDS = (
    "technical_score", "technical_as_of", "technical_engine", "signal", "signal_label",
    "signal_since",
    "price_at_signal", "signal_return_pct", "pa_bias", "pa_phase", "pa_structure", "pa_breakout",
    "pa_setup", "pa_quality", "rel_volume", "div_rsi_bullish", "div_rsi_bearish",
    "div_efi_bullish", "div_efi_bearish", "div_latest", "top_candlestick", "top_chart_pattern",
    "top_pattern", "strategy_action", "strategy_conviction",
)


def _f(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def _local_day(stamp: int, offset: int) -> str:
    """The session's date on the exchange's own calendar.

    Not the UTC date. Sydney opens at 23:00 UTC the day before during daylight saving, so filing
    bars by UTC put every summer session a day early: Mondays on Sundays, and no Fridays at all.
    """
    return datetime.fromtimestamp(stamp + offset, UTC).date().isoformat()


def _with_session_close(closes: list, highs: list | None, ts: list, meta: dict) -> list:
    """Fill the close of the newest session when Yahoo has left it null.

    For hours after a market shuts, Yahoo serves that day's bar with its open, high, low and volume
    but no close, and carries the close in `meta`. Dropping the bar read Saudi, Dubai and most of
    India a session behind on the day-end run. The market time must fall on that session's date:
    PSX's meta stopped in July 2024, and a close from there on a bar from today would be invented.
    """
    price, traded = meta.get("regularMarketPrice"), meta.get("regularMarketTime")
    if closes[-1] is not None or price is None or not traded or len(ts) != len(closes):
        return closes
    if not highs or highs[-1] is None:
        return closes
    offset = meta.get("gmtoffset") or 0
    if _local_day(ts[-1], offset) != _local_day(traded, offset):
        return closes
    return [*closes[:-1], price]


def _session_open_since(meta: dict, now: float) -> int | None:
    """When the session in progress began, or None if the market is shut.

    A session still trading is not a bar yet: it has part of a day's volume and a close that will
    change. The scheduled run starts hours late and lands mid-session in Sydney, and the engine
    judges a breakout on the volume of its break bar.
    """
    period = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    start, end = period.get("start"), period.get("end")
    return start if start and end and start <= now < end else None


def fetch_history(sym: str, client: httpx.Client, host: str = "query1"):
    """chart-v8 daily OHLCV → (dates, open, high, low, close, volume), or None.

    `dates` are ISO strings aligned with the arrays (for signal-inception backtesting).
    `open` is carried so candlestick patterns can be detected from the same fetch."""
    try:
        resp = client.get(_CHART.format(host=host, sym=sym), headers={"User-Agent": _UA},
                          timeout=20)
        resp.raise_for_status()
        res = resp.json()["chart"]["result"][0]
        ts = res.get("timestamp") or []
        q = res["indicators"]["quote"][0]
        opens = q.get("open")
        highs, lows, closes, vols = q.get("high"), q.get("low"), q.get("close"), q.get("volume")
        if not closes:
            return None
        meta = res.get("meta") or {}
        closes = _with_session_close(closes, highs, ts, meta)
        trading_since = _session_open_since(meta, time.time())
        bars = [
            (highs[i], lows[i], closes[i], vols[i] if vols else None,
             ts[i] if i < len(ts) else None, opens[i] if opens else None)
            for i in range(len(closes))
            if closes[i] is not None
            and not (trading_since and i < len(ts) and ts[i] >= trading_since)
        ]
        if len(bars) < MIN_BARS:
            return None
        close = np.array([b[2] for b in bars], dtype=float)
        high = np.array([b[0] if b[0] is not None else b[2] for b in bars], dtype=float)
        low = np.array([b[1] if b[1] is not None else b[2] for b in bars], dtype=float)
        vol = np.array([b[3] if b[3] is not None else 0.0 for b in bars], dtype=float)
        open_ = np.array([b[5] if b[5] is not None else b[2] for b in bars], dtype=float)
        offset = meta.get("gmtoffset") or 0
        dates = [_local_day(b[4], offset) if b[4] else "" for b in bars]
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


def blend(fund, tech, mom, qual, risk, regime, de) -> tuple[float | None, float, dict]:
    """The published composite: (score, coverage, legs present). The one definition of it.

    score_unify calls this too. It used to reblend on its own after this pass, without the regime
    overlay and without the rule below, and left the signal behind: 777 rows ended up with a
    signal from a different band to the composite beside it, and technical-only names came back
    as their raw technical score.
    """
    if fund is None and mom is None and qual is None and risk is None:
        if tech is None:
            return None, 0.0, {}
        # Technical-only name: shrink toward neutral so a raw technical score can't masquerade
        # as a full composite (keeps the expanded tail from flooding the top).
        return (round(50.0 + (tech - 50.0) * WEIGHTS["technical"], 2), WEIGHTS["technical"],
                {"technical": tech})
    base, coverage, present = _reblend(fund, tech, mom, qual, risk)
    if base is None:
        return None, 0.0, {}
    composite, _breakdown = apply_regime_modifier(base, regime, de)
    return composite, coverage, present


def _composite_at(dates, open_, high, low, close, vol, k, legs, regime, de):
    """Recomputed (composite, coverage, present) using only the first k bars, or None.

    Takes dates and opens now because the price-action engine reads candles, not a close
    series: the shape of a bar is half of what it judges. The PSX portal path has neither, and
    passes close for all four - the engine degrades to structure and volume, which is the
    honest result for close-only data rather than a fabricated candle.
    """
    read = analyse_price_action(dates[:k], open_[:k], high[:k], low[:k], close[:k], vol[:k])
    tech = read.score
    if tech is None:
        return None
    fund, mom, qual, risk = legs
    base, cov, present = _reblend(fund, _f(tech), mom, qual, risk)
    if base is None:
        return None
    comp, _ = apply_regime_modifier(base, regime, de)
    return comp, cov, present


def _signal_value_at(dates, open_, high, low, close, vol, k, legs, regime, de) -> str | None:
    """The derived signal value using only the first k bars (for inception backtesting)."""
    c = _composite_at(dates, open_, high, low, close, vol, k, legs, regime, de)
    if c is None:
        return None
    comp, cov, present = c
    return derive_signal(comp, cov, present).signal.value


def _signal_since(dates, open_, high, low, close, vol, legs, regime, de, current,
                  lookback=250):
    """Walk back over history to the earliest day the current signal has held → (date, close).
    Real inception, not fabricated — capped at `lookback` trading days."""
    n = len(close)
    floor = max(MIN_BARS - 1, n - 1 - lookback)
    inception = floor
    for j in range(n - 1, floor - 1, -1):
        s = _signal_value_at(dates, open_, high, low, close, vol, j + 1, legs, regime, de)
        if s != current:  # includes None → treat as boundary
            inception = j + 1
            break
        inception = j
    idx = max(0, min(inception, n - 1))
    d = dates[idx] if idx < len(dates) and dates[idx] else None
    return d, float(close[idx])


def _on_exchange_closes(symbol: str, yahoo):
    """Yahoo's PSX candles, kept only where they agree with our exchange-reconciled closes.

    The pack holds closes and, at best, volume - no opens, highs or lows. Scoring on that is not
    a milder version of the same read: swings are found on highs and lows, and for OGDC and MEBL
    the close-only score came out 12 and 10 points away from the real one. So candles come from
    Yahoo, and the pack decides whether to believe them.

    A bar is dropped when the pack contradicts it. A day the pack has no bar for stays: 65 names
    have a hole from 25 Sep to 4 Nov 2026 and nothing there disagrees with Yahoo.

    Returns None rather than a partial read when the series is unusable:

      * too few bars actually confirmed by the pack, which is also how a series re-based by a
        split is caught - every shared day disagrees;
      * a last bar well behind the pack - the names Yahoo stopped carrying;
      * a newest exchange price further from Yahoo's last close than the daily limit could
        explain - GIL read 125.85 on Yahoo against 1,000 on the exchange;
      * no volume at all in the recent window - a flat, untraded line is not a chart.
    """
    from app.ingestion.price_pack import packed_bars

    if yahoo is None:
        return None
    packed = packed_bars("psx", symbol)
    if not packed:
        return None
    dates, open_, high, low, close, vol = yahoo
    keep, confirmed = [], 0
    for i, day in enumerate(dates):
        row = packed.get(day)
        if row is None or not row[4]:
            keep.append(i)
        elif abs(float(close[i]) / float(row[4]) - 1.0) <= PSX_BAR_TOLERANCE:
            keep.append(i)
            confirmed += 1
    if confirmed < MIN_BARS:
        return None
    newest = max(packed)
    lag = (datetime.fromisoformat(newest) - datetime.fromisoformat(dates[keep[-1]])).days
    if lag > PSX_MAX_LAG_DAYS:
        return None
    if abs(float(packed[newest][4]) / float(close[keep[-1]]) - 1.0) > PSX_MAX_GAP:
        return None
    if not np.any(vol[keep][-PSX_VOLUME_WINDOW:] > 0):
        return None
    return [dates[i] for i in keep], open_[keep], high[keep], low[keep], close[keep], vol[keep]


def _yahoo_says(sym: str, client: httpx.Client) -> str:
    """What Yahoo actually answered, because fetch_history can only say "nothing".

    HUBC, AHCL, AVN, ALTN and BNL came back on every run from here and on none from CI, retry
    included, and a job's logs need a token to read. This goes in the annotation instead.
    """
    try:
        resp = client.get(_CHART.format(host="query1", sym=sym), headers={"User-Agent": _UA},
                          timeout=20)
        return f"{sym}: HTTP {resp.status_code} {resp.text[:90]!r}"
    except httpx.HTTPError as exc:
        return f"{sym}: {type(exc).__name__}"


def _read_is_recent(r: dict) -> bool:
    try:
        seen = datetime.fromisoformat(str(r.get("technical_as_of"))[:10]).date()
    except ValueError:
        return False
    return (datetime.now(UTC).date() - seen).days <= PSX_KEEP_READ_DAYS


def _withdraw_read(r: dict, company: Path, regime_map: dict) -> None:
    """Clear the technical read and signal of a company we cannot chart.

    Leaving the old numbers would be the worse failure: this is how Pakistan came to publish
    technical scores from 10 August, on a retired engine, for three months. A blank says "no
    read"; a stale score says something false with full confidence.
    """
    fund, qual, risk = (_f(r.get("fundamental_score")), _f(r.get("quality_score")),
                        _f(r.get("risk_score")))
    composite, _cov, _present = blend(fund, None, None, qual, risk,
                                      regime_map.get(r.get("region")),
                                      _f(r.get("debt_to_equity")))
    r["composite_score"] = composite
    for key in _READ_FIELDS:
        r[key] = None
    cf = safe_file(company, f"{r['provider_symbol']}.json")
    if cf is None or not cf.exists():
        return
    try:
        d = json.loads(cf.read_text(encoding="utf-8"))
        if isinstance(d.get("scores"), dict):
            d["scores"]["technical"] = None
            d["scores"]["composite"] = composite
            d["scores"].pop("momentum", None)
        d.pop("price_action", None)
        d.pop("strategy", None)
        d["divergences"] = []
        d["patterns"] = []
        d["signal"] = None
        cf.write_text(json.dumps(d), encoding="utf-8")
    except (OSError, json.JSONDecodeError):
        pass


# The index whose performance each market is measured against. Relative strength is meaningless
# without one, and these series are already maintained in the global price pack by
# `refresh-indices` on every run - so this costs no extra fetch.
BENCHMARK = {
    "us": "^GSPC", "india": "^NSEI", "australia": "^AXJO",
    "gcc": "^TASI.SR", "psx": "^KSE100", "dfm": "DFMGI.AE",
}
_BENCH_CACHE: dict[str, list] = {}


def _benchmark_bars(region: str) -> list:
    """Benchmark closes as Bar objects, loaded once per region per process."""
    if region in _BENCH_CACHE:
        return _BENCH_CACHE[region]
    symbol = BENCHMARK.get(region or "")
    out: list = []
    if symbol:
        from app.engines.price_action.candles import Bar
        from app.ingestion.price_pack import packed_bars

        rows = packed_bars("global", symbol)
        for day in sorted(rows):
            _d, _o, _h, _l, close, _v = rows[day]
            if close is not None:
                out.append(Bar(date=day, open=close, high=close, low=close,
                               close=close, volume=None))
    if not out and symbol:
        # Loud, because a silently absent benchmark makes relative strength null for a whole
        # market and the score renormalises around it without complaint - exactly the kind of
        # invisible degradation this codebase keeps producing.
        log.warning("relative strength: no packed history for benchmark %s (%s)", symbol, region)
    _BENCH_CACHE[region] = out
    return out


def refresh_technicals(
    data_dir: str | Path,
    skip_regions: tuple[str, ...] = (),
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
        # Once more, slowly, on the other host. fetch_history cannot tell a refusal from a symbol
        # with no data, and the refusals are the ones this recovers.
        missed = [s for s in syms if s not in hist]
        if missed:
            time.sleep(RETRY_PAUSE_SECONDS)
            with ThreadPoolExecutor(max_workers=RETRY_WORKERS) as pool:
                results = pool.map(lambda s: fetch_history(s, client, host="query2"), missed)
                for sym, h in zip(missed, results, strict=False):
                    if h is not None:
                        hist[sym] = h
            log.info("refresh-technicals: retry recovered %d of %d",
                     sum(1 for s in missed if s in hist), len(missed))
        still = [s for s in missed if s not in hist and s.endswith(".KA")]
        if still:
            samples = [_yahoo_says(s, client) for s in still[:WHY_SAMPLE]]
            print(f"::warning::refresh-technicals: Yahoo's answer for names it did not serve: "
                  f"{samples}", flush=True)
    finally:
        client.close()

    # Keep what we just downloaded. chart-v8 hands back a year of daily bars per symbol and this
    # pass used to discard every one of them after scoring, so the price history only ever grew
    # on the machine that ran a separate fetch - and CI, which has no raw CSVs at all, could
    # price nothing and rebuilt every quarterly history as zero trades. Folding the closes in
    # here costs no extra request and advances the store on every run, everywhere.
    try:
        from app.ingestion.price_pack import merge_series

        by_region: dict[str, dict[str, dict[str, float]]] = {}
        for r in targets:
            h = hist.get(r.get("provider_symbol"))
            if not h or not r.get("region") or not r.get("symbol"):
                continue
            if r["region"] == "psx":
                continue  # Only refresh_psx_daily writes this pack, and only what reconciles.
            dates, _o, _h, _l, closes, _v = h
            points = {d: c for d, c in zip(dates, closes, strict=False) if d and c}
            if points:
                by_region.setdefault(r["region"], {})[r["symbol"]] = points
        for region, series in by_region.items():
            log.info("price-pack(%s): %s", region, merge_series(region, series))
    except Exception as exc:  # noqa: BLE001 - storing history must never fail the refresh
        log.warning("price-pack from technicals failed: %s", exc)

    company = out / "company"
    uncharted = []
    unserved = []     # Yahoo gave us nothing. fetch_history cannot say whether it never will.
    for r in targets:
        if r.get("region") != "psx":
            continue
        sym = r["provider_symbol"]
        if sym not in hist:
            unserved.append(str(r.get("symbol")))
        checked = _on_exchange_closes(str(r.get("symbol")), hist.pop(sym, None))
        if checked is not None:
            hist[sym] = checked
        elif not _read_is_recent(r):
            uncharted.append(r)

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
        read = analyse_price_action(dates, open_, high, low, close, vol,
                                    benchmark_bars=_benchmark_bars(r.get("region")))
        tech = read.score
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
            strategy = strategy_evaluate(statements, high, low, close, vol,
                                         sector=r.get("sector"), region=r.get("region"),
                                         industry=r.get("industry")).as_dict()
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
        # No momentum leg any more. It was computed from the indicator object this pass no
        # longer builds, and its inputs were the banned ones. Anything momentum was measuring -
        # whether price is advancing, and with what force - the price-action engine now reads
        # directly off structure and volume, so a second smoothed opinion added nothing.
        mom = None
        qual, risk = _f(sc.get("quality")), _f(sc.get("risk"))
        regime = regime_map.get(r.get("region"))
        de = _f(r.get("debt_to_equity"))
        composite, coverage, present = blend(fund, _f(tech), mom, qual, risk, regime, de)
        if composite is None:
            continue
        sig = derive_signal(composite, coverage, present)

        # Backtest the real signal-inception date + return-since (fixes "all show today").
        legs = (fund, _f(sc.get("momentum")), _f(sc.get("quality")), _f(sc.get("risk")))
        since, price_at = _signal_since(
            dates, open_, high, low, close, vol, legs, regime, de, sig.signal.value
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
        # A row's first read on this engine has nothing comparable before it, so the change is a
        # re-baseline and not a move. Without this, the run that brought PSX onto this engine
        # would have filled the Movers page with 356 "upgrades and downgrades" that happened on
        # no chart.
        comparable = r.get("technical_engine") == TECHNICAL_ENGINE
        if comparable:
            _record_signal_move(smoves, r, old_sig, new_sig, sig.label, composite, cur_price,
                                today)
        r["technical_score"] = round(tech, 2)
        # The last bar the read saw, so a frozen chart is a failed check rather than a score
        # that merely stopped changing. See freshness.check_snapshot.
        r["technical_as_of"] = dates[-1]
        r["technical_engine"] = TECHNICAL_ENGINE
        # RSI and EFI divergences, for the technical filter page. Computed from the SAME daily
        # bars this pass already downloaded, so the filter costs no extra request and refreshes
        # every day the refresh runs. Kept out of the technical score deliberately - see
        # engines/divergence.
        from app.engines.divergence.engine import summarise as divergences

        _div = divergences(dates, high, low, close, vol)
        r["div_rsi_bullish"] = _div["rsi_bullish"]
        r["div_rsi_bearish"] = _div["rsi_bearish"]
        r["div_efi_bullish"] = _div["efi_bullish"]
        r["div_efi_bearish"] = _div["efi_bearish"]
        r["div_latest"] = _div["latest"]
        # Screener columns: enough of the read to sort and filter on without opening the page.
        r["pa_bias"] = read.bias
        r["pa_phase"] = read.phase
        r["pa_structure"] = read.structure_daily
        r["pa_breakout"] = read.breakout_status
        r["pa_setup"] = read.setup.kind
        r["pa_quality"] = read.quality
        r["rel_volume"] = read.volume.get("relative")
        r["composite_score"] = composite
        r["signal"] = new_sig
        r["signal_label"] = sig.label
        r["signal_since"] = since or today
        r["price_at_signal"] = round(price_at, 4) if price_at else None
        r["signal_return_pct"] = ret

        if comparable and old is not None and abs(composite - old) >= 1.0:
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
                    # The momentum leg is retired along with the indicators it came from.
                    d["scores"].pop("momentum", None)
                # The whole read, not just the number. A technical score with no chart
                # reasoning behind it is the thing the brief is written against: the page can
                # now show the structure, the levels and their evidence, the volume verdict and
                # the setup - or NO TRADE and what would change it.
                d["divergences"] = _div["items"]
                d["price_action"] = {
                    "score": read.score, "bias": read.bias, "quality": read.quality,
                    "phase": read.phase, "phase_confidence": read.phase_confidence,
                    "structure_daily": read.structure_daily,
                    "structure_weekly": read.structure_weekly,
                    "breakout_status": read.breakout_status,
                    "components": read.components, "zones": read.zones,
                    "volume": read.volume, "candles": read.candle_notes,
                    # Relative strength is a fifth of the score, so it ships with its reasoning.
                    # A leg that moves the number without showing why is unauditable.
                    "relative": read.relative,
                    "summary": read.summary, "what_changes_it": read.what_changes_it,
                    "notes": read.notes,
                    "setup": {
                        "kind": read.setup.kind,
                        "aggressive_entry": read.setup.aggressive_entry,
                        "conservative_entry": read.setup.conservative_entry,
                        "stop": read.setup.stop, "target_1": read.setup.target_1,
                        "target_2": read.setup.target_2,
                        "major_target": read.setup.major_target,
                        "risk_reward": read.setup.risk_reward,
                        "rationale": read.setup.rationale,
                    },
                }
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

    for r in uncharted:
        _withdraw_read(r, company, regime_map)
    if uncharted:
        names = sorted(str(r.get("symbol")) for r in uncharted)
        rejected = sorted(set(names) - set(unserved))
        # An annotation, because job logs need a token to read and this count must be visible.
        # Split by reason: HUBC went blank for a run with nothing to say which of these it was.
        print(f"::warning::refresh-technicals: {len(names)} PSX names carry no signal. "
              f"{len(names) - len(rejected)} not served by Yahoo: "
              f"{sorted(set(names) & set(unserved))[:40]}. {len(rejected)} failed the check "
              f"against the exchange: {rejected[:20]}", flush=True)

    (out / "screener.json").write_text(json.dumps(rows), encoding="utf-8")
    _update_movers(out, deltas, today)
    _update_signal_moves(out, smoves, today)

    result = {
        "targets": len(targets), "quoted": len(hist),
        "updated": updated, "uncharted": len(uncharted), "movers": len(deltas),
        "signal_moves": len(smoves),
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
