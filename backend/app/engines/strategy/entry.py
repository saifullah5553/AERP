"""Price-action entry timing — "has this quality business just STARTED moving up?"

The point is to buy early in a move, not after it. The previous engine rewarded names that were
already extended (near 52-week highs, high RSI, strong ADX) and the factor backtest measured
exactly those inputs as negative predictors over 60 days: momentum IC -0.094,
pct_from_52w_high -0.087, adx -0.086. Buying strength late is what mean-reverted.

So this module inverts that logic:

  TRIGGERS (need at least one)
    * Base breakout   - price clears a multi-week consolidation high
    * Trend reclaim   - price crosses back above the 50-day average from below
    * Higher lows     - a rising sequence of swing lows off a bottom

  CONFIRMATION
    * Volume expansion on the move (participation, not drift)
    * Price above the 200-day average, or reclaiming it (long-term trend intact)

  EXTENSION VETO (rejects the late entries the old engine loved)
    * Price far above the 50-day average
    * RSI already overbought
    * Sitting on the 52-week high after a long run

Pure NumPy on OHLCV, no look-ahead: every value comes from the bars supplied.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass(slots=True)
class EntryResult:
    triggered: bool
    score: float | None                  # 0-100 timing quality, None when not computable
    triggers: list[str] = field(default_factory=list)
    vetoes: list[str] = field(default_factory=list)
    metrics: dict[str, float | None] = field(default_factory=dict)


def _sma(a: np.ndarray, n: int) -> float | None:
    return float(a[-n:].mean()) if len(a) >= n else None


def _ema(a: np.ndarray, n: int) -> float | None:
    """Exponential moving average — reacts faster than the SMA, which is what you want when
    the point is to notice a move starting rather than confirm one that already has."""
    if len(a) < n:
        return None
    k = 2.0 / (n + 1.0)
    e = float(a[-(n * 3):][0]) if len(a) >= n * 3 else float(a[0])
    for v in a[-(n * 3):] if len(a) >= n * 3 else a:
        e = float(v) * k + e * (1 - k)
    return e


def _trendline_break(high: np.ndarray, close: np.ndarray, lookback: int = 60) -> bool:
    """True when price closes above a falling trendline drawn across recent highs.

    Fits a least-squares line through the highs of the lookback window; a negative slope means
    the stock has been making lower highs, and a close above that line is the classic
    downtrend-break entry.
    """
    if len(close) < lookback:
        return False
    seg = high[-lookback:]
    x = np.arange(len(seg), dtype=float)
    slope, intercept = np.polyfit(x, seg.astype(float), 1)
    if slope >= 0:  # not a downtrend - a different setup, handled by the breakout trigger
        return False
    projected = slope * (len(seg) - 1) + intercept
    return float(close[-1]) > projected


def _rsi(close: np.ndarray, n: int = 14) -> float | None:
    if len(close) < n + 1:
        return None
    d = np.diff(close[-(n + 1):])
    gain = float(d[d > 0].sum()) / n
    loss = float(-d[d < 0].sum()) / n
    if loss == 0:
        return 100.0
    rs = gain / loss
    return 100.0 - 100.0 / (1.0 + rs)


def assess_entry(
    high: np.ndarray, low: np.ndarray, close: np.ndarray, volume: np.ndarray,
    base_lookback: int = 60, breakout_buffer: float = 0.02,
) -> EntryResult:
    """Detect the start of an advance in a quality name."""
    n = len(close)
    if n < 60:
        return EntryResult(triggered=False, score=None, vetoes=["insufficient_history"])

    px = float(close[-1])
    sma50 = _sma(close, 50)
    sma200 = _sma(close, 200)
    rsi = _rsi(close)
    metrics: dict[str, float | None] = {"price": px, "sma50": sma50, "sma200": sma200, "rsi": rsi}

    triggers: list[str] = []
    vetoes: list[str] = []

    # --- Trigger 1: breakout from a consolidation base -------------------------------
    # Exclude the last 5 bars from the base so the breakout bar itself doesn't set the high.
    base = close[-base_lookback:-5] if n >= base_lookback else close[:-5]
    if len(base) >= 20:
        base_high = float(base.max())
        base_low = float(base.min())
        # A base is only meaningful if the range was reasonably tight beforehand.
        tight = (base_high - base_low) / base_high < 0.35 if base_high else False
        metrics["base_high"] = base_high
        if tight and px > base_high * (1 + breakout_buffer):
            triggers.append("base_breakout")

    # --- Trigger 2: reclaiming the 50-day from below ---------------------------------
    if sma50 is not None and len(close) >= 55:
        prior = close[-10:-1]
        prior_sma50 = _sma(close[:-1], 50)
        if prior_sma50 is not None and px > sma50 and float(prior.min()) < prior_sma50:
            triggers.append("reclaimed_sma50")

    # --- Trigger 3: higher lows (accumulation structure) -----------------------------
    if n >= 60:
        seg = low[-60:]
        thirds = [seg[:20], seg[20:40], seg[40:]]
        lows = [float(s.min()) for s in thirds if len(s)]
        if len(lows) == 3 and lows[0] < lows[1] < lows[2]:
            triggers.append("higher_lows")

    # --- Trigger 4: reclaiming the 20 EMA --------------------------------------------
    # The fast average: catches a move turning up well before the 50-day confirms it.
    ema20 = _ema(close, 20)
    metrics["ema20"] = ema20
    if ema20 is not None and px > ema20:
        prev_ema20 = _ema(close[:-3], 20) if n > 23 else None
        if prev_ema20 is not None and float(close[-4]) < prev_ema20:
            triggers.append("crossed_above_ema20")
        elif "base_breakout" not in triggers:
            triggers.append("above_ema20")

    # --- Trigger 5: downtrend trendline break ----------------------------------------
    if _trendline_break(high, close):
        triggers.append("trendline_break")

    # --- Confirmation / Trigger 6: volume participation -------------------------------
    vol_ratio = None
    if len(volume) >= 50 and volume[-50:].mean() > 0:
        vol_ratio = float(volume[-5:].mean() / volume[-50:].mean())
        metrics["volume_ratio"] = vol_ratio
        # Rising volume is itself a signal that something is happening - accumulation often
        # shows up in the tape before it shows up in the price structure.
        if vol_ratio >= 1.5 and px > (ema20 or px):
            triggers.append("volume_expansion")

    # --- Extension checks -------------------------------------------------------------
    # HARD vetoes block the entry outright: the move is so far gone that buying it is chasing.
    # SOFT cautions only mark the score down - being mildly extended or briefly overbought is
    # normal early in a strong advance, and blocking on it would filter out the best entries.
    cautions: list[str] = []
    ext = None
    if sma50:
        ext = (px - sma50) / sma50
        metrics["pct_above_sma50"] = ext
        if ext > 0.35:
            vetoes.append("far_extended_above_sma50")   # hard: chasing
        elif ext > 0.20:
            cautions.append("extended_above_sma50")     # soft
    if rsi is not None:
        if rsi > 85:
            vetoes.append("extremely_overbought")       # hard
        elif rsi > 72:
            cautions.append("overbought_rsi")           # soft
    if n >= 250:
        high_52w = float(high[-250:].max())
        metrics["pct_from_52w_high"] = (px - high_52w) / high_52w if high_52w else None
        run = (px - float(close[-250:].min())) / max(float(close[-250:].min()), 1e-9)
        if high_52w and px >= high_52w * 0.995 and run > 2.0:
            vetoes.append("at_52w_high_after_parabolic_run")  # hard: tripled off the low
        elif high_52w and px >= high_52w * 0.995 and run > 1.0:
            cautions.append("at_52w_high_after_long_run")     # soft

    # Long-term trend: a decisive break below the 200-day is a hard stop, but a stock basing
    # just under it can still be an early entry, so only a clear break blocks.
    if sma200 is not None and px < sma200 * 0.90:
        vetoes.append("well_below_200dma")

    metrics["cautions"] = float(len(cautions))
    triggered = bool(triggers) and not vetoes

    # Timing quality: reward early, well-participated entries close to the base.
    score = None
    if sma50:
        s = 40.0 + 20.0 * len(triggers)
        if vol_ratio is not None:
            s += 15.0 if vol_ratio >= 1.3 else (7.0 if vol_ratio >= 1.0 else 0.0)
        if ext is not None:
            s += 15.0 if ext <= 0.08 else (7.0 if ext <= 0.15 else 0.0)
        if sma200 is not None and px > sma200:
            s += 10.0
        s -= 25.0 * len(vetoes)
        s -= 8.0 * len(cautions)  # soft: marks the entry down without blocking it
        score = round(max(0.0, min(100.0, s)), 2)

    return EntryResult(triggered=triggered, score=score, triggers=triggers,
                       vetoes=vetoes + cautions, metrics=metrics)
