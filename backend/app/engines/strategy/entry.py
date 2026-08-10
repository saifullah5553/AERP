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



def assess_entry(
    high: np.ndarray, low: np.ndarray, close: np.ndarray, volume: np.ndarray,
    base_lookback: int = 60, breakout_buffer: float = 0.02,
) -> EntryResult:
    """Detect the start of an advance in a quality name."""
    n = len(close)
    if n < 60:
        return EntryResult(triggered=False, score=None, vetoes=["insufficient_history"])

    px = float(close[-1])
    # Measurements, not indicators: the highest and lowest close over a window, and how far
    # price sits from each. The brief allows these explicitly - they are things you can read off
    # a chart with a ruler - where a moving average or an RSI reading is a constructed series.
    high_52w = float(close[-250:].max()) if n >= 250 else float(close.max())
    low_60 = float(close[-60:].min())
    pct_from_high = (px / high_52w - 1) * 100 if high_52w else None
    pct_above_low = (px / low_60 - 1) * 100 if low_60 else None
    metrics: dict[str, float | None] = {
        "price": px, "high_52w": high_52w, "low_60": low_60,
        "pct_from_52w_high": pct_from_high, "pct_above_60d_low": pct_above_low,
    }

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

    # --- Trigger 2: reclaiming a level price had lost ---------------------------------
    # Was "reclaimed the 50-day". Same idea without the average: price spent recent sessions
    # below a level it had been holding, and has now closed back above it. The level is the
    # prior month's floor, which is a price the market actually traded at rather than a
    # rolling mean of prices it did not.
    if n >= 60:
        floor_before = float(close[-60:-20].min())
        dipped = float(close[-10:-1].min()) < floor_before
        if dipped and px > floor_before:
            triggers.append("reclaimed_prior_floor")

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
    # Extension measured against a PRICE the market traded - the 60-day low - instead of
    # against a moving average or an RSI band. The veto is doing the same job it always did
    # (do not chase a move that has already run) using a number you can point at on the chart.
    ext = None
    if pct_above_low is not None:
        ext = pct_above_low / 100.0
        metrics["pct_above_60d_low"] = pct_above_low
        if ext > 0.60:
            vetoes.append("far_extended_above_60d_low")   # hard: chasing
        elif ext > 0.35:
            cautions.append("extended_above_60d_low")     # soft
    if n >= 250:
        high_52w = float(high[-250:].max())
        metrics["pct_from_52w_high"] = (px - high_52w) / high_52w if high_52w else None
        run = (px - float(close[-250:].min())) / max(float(close[-250:].min()), 1e-9)
        if high_52w and px >= high_52w * 0.995 and run > 2.0:
            vetoes.append("at_52w_high_after_parabolic_run")  # hard: tripled off the low
        elif high_52w and px >= high_52w * 0.995 and run > 1.0:
            cautions.append("at_52w_high_after_long_run")     # soft

    # Long-term trend, without the 200-day. A stock deep under its own yearly high is in a
    # downtrend whatever an average says, and "30% off the 52-week high" is a measurement of
    # where price has actually been rather than a constructed line.
    if pct_from_high is not None and pct_from_high < -30.0:
        vetoes.append("far_below_52w_high")

    metrics["cautions"] = float(len(cautions))
    triggered = bool(triggers) and not vetoes

    # Timing quality: reward early, well-participated entries close to the base.
    score = None
    if pct_above_low is not None:
        s = 40.0 + 20.0 * len(triggers)
        if vol_ratio is not None:
            s += 15.0 if vol_ratio >= 1.3 else (7.0 if vol_ratio >= 1.0 else 0.0)
        if ext is not None:
            s += 15.0 if ext <= 0.08 else (7.0 if ext <= 0.15 else 0.0)
        # In the upper half of its yearly range: a positional tailwind, measured off real
        # highs and lows rather than an average.
        if pct_from_high is not None and pct_from_high > -25.0:
            s += 10.0
        s -= 25.0 * len(vetoes)
        s -= 8.0 * len(cautions)  # soft: marks the entry down without blocking it
        score = round(max(0.0, min(100.0, s)), 2)

    return EntryResult(triggered=triggered, score=score, triggers=triggers,
                       vetoes=vetoes + cautions, metrics=metrics)
