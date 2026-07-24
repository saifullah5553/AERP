"""Technical-indicator computation from OHLCV, in pure NumPy (no TA-Lib).

Each function returns the latest value(s) and yields ``None`` when there is too
little history to compute honestly. :func:`compute_indicators` assembles the full
:class:`IndicatorSet` the technical engine persists and scores.

Formulas follow standard definitions: Wilder smoothing for RSI/ATR/ADX, 12/26/9
MACD, 20/2 Bollinger, 9/26/52 Ichimoku, 10/3 SuperTrend.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

TRADING_DAYS = 252


@dataclass(slots=True)
class IndicatorSet:
    # Moving averages
    sma_20: float | None = None
    sma_50: float | None = None
    sma_200: float | None = None
    ema_12: float | None = None
    ema_26: float | None = None
    ema_50: float | None = None
    # Oscillators / trend
    rsi_14: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    macd_hist: float | None = None
    adx_14: float | None = None
    atr_14: float | None = None
    supertrend: float | None = None
    supertrend_dir: int | None = None
    # Ichimoku
    ichimoku_conversion: float | None = None
    ichimoku_base: float | None = None
    ichimoku_span_a: float | None = None
    ichimoku_span_b: float | None = None
    # Volume / flow
    vwap: float | None = None
    obv: float | None = None
    mfi_14: float | None = None
    # Bands / channels
    bb_upper: float | None = None
    bb_middle: float | None = None
    bb_lower: float | None = None
    keltner_upper: float | None = None
    keltner_lower: float | None = None
    donchian_upper: float | None = None
    donchian_lower: float | None = None
    # Derived
    relative_strength: float | None = None
    high_52w: float | None = None
    low_52w: float | None = None
    pct_from_52w_high: float | None = None
    trend_strength: float | None = None
    momentum: float | None = None
    volatility: float | None = None
    breakout_strength: float | None = None
    # Scoring aids (not persisted as columns)
    last_close: float | None = None
    obv_rising: bool | None = None


def sma(x: np.ndarray, n: int) -> float | None:
    return float(np.mean(x[-n:])) if len(x) >= n else None


def ema_series(x: np.ndarray, n: int) -> np.ndarray:
    alpha = 2.0 / (n + 1.0)
    out = np.empty_like(x, dtype=float)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = alpha * x[i] + (1 - alpha) * out[i - 1]
    return out


def ema(x: np.ndarray, n: int) -> float | None:
    return float(ema_series(x, n)[-1]) if len(x) >= n else None


def _wilder(values: np.ndarray, n: int) -> np.ndarray:
    """Wilder's smoothing (RMA) of a series; output aligned to input length."""
    out = np.full_like(values, np.nan, dtype=float)
    if len(values) < n:
        return out
    out[n - 1] = np.mean(values[:n])
    for i in range(n, len(values)):
        out[i] = (out[i - 1] * (n - 1) + values[i]) / n
    return out


def rsi(close: np.ndarray, n: int = 14) -> float | None:
    if len(close) < n + 1:
        return None
    delta = np.diff(close)
    gains = np.clip(delta, 0, None)
    losses = -np.clip(delta, None, 0)
    avg_gain = _wilder(gains, n)[-1]
    avg_loss = _wilder(losses, n)[-1]
    if np.isnan(avg_gain) or np.isnan(avg_loss):
        return None
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100 - 100 / (1 + rs))


def true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
    return tr


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int = 14) -> float | None:
    if len(close) < n + 1:
        return None
    val = _wilder(true_range(high, low, close), n)[-1]
    return None if np.isnan(val) else float(val)


def adx(
    high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int = 14
) -> tuple[float | None, float | None, float | None]:
    """Return (ADX, +DI, -DI)."""
    if len(close) < 2 * n + 1:
        return None, None, None
    up_move = high[1:] - high[:-1]
    down_move = low[:-1] - low[1:]
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr = true_range(high, low, close)[1:]

    atr_s = _wilder(tr, n)
    plus_di = 100 * _wilder(plus_dm, n) / atr_s
    minus_di = 100 * _wilder(minus_dm, n) / atr_s
    denom = plus_di + minus_di
    dx = 100 * np.abs(plus_di - minus_di) / np.where(denom == 0, np.nan, denom)
    adx_val = _wilder(dx[~np.isnan(dx)], n)
    if len(adx_val) == 0 or np.isnan(adx_val[-1]):
        return None, _last(plus_di), _last(minus_di)
    return float(adx_val[-1]), _last(plus_di), _last(minus_di)


def macd(close: np.ndarray) -> tuple[float | None, float | None, float | None]:
    if len(close) < 26:
        return None, None, None
    macd_line = ema_series(close, 12) - ema_series(close, 26)
    signal = ema_series(macd_line, 9)
    return float(macd_line[-1]), float(signal[-1]), float(macd_line[-1] - signal[-1])


def supertrend(
    high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 10, mult: float = 3.0
) -> tuple[float | None, int | None]:
    if len(close) < period + 1:
        return None, None
    atr_s = _wilder(true_range(high, low, close), period)
    hl2 = (high + low) / 2
    upper = hl2 + mult * atr_s
    lower = hl2 - mult * atr_s
    n = len(close)
    final_upper = np.copy(upper)
    final_lower = np.copy(lower)
    direction = np.ones(n, dtype=int)
    for i in range(1, n):
        if np.isnan(atr_s[i]):
            continue
        final_upper[i] = (
            min(upper[i], final_upper[i - 1])
            if close[i - 1] <= final_upper[i - 1]
            else upper[i]
        )
        final_lower[i] = (
            max(lower[i], final_lower[i - 1])
            if close[i - 1] >= final_lower[i - 1]
            else lower[i]
        )
        if close[i] > final_upper[i - 1]:
            direction[i] = 1
        elif close[i] < final_lower[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]
    st = final_lower[-1] if direction[-1] == 1 else final_upper[-1]
    return (None if np.isnan(st) else float(st)), int(direction[-1])


def ichimoku(
    high: np.ndarray, low: np.ndarray
) -> tuple[float | None, float | None, float | None, float | None]:
    def mid(n: int) -> float | None:
        if len(high) < n:
            return None
        return float((np.max(high[-n:]) + np.min(low[-n:])) / 2)

    conv, base, span_b = mid(9), mid(26), mid(52)
    span_a = (conv + base) / 2 if conv is not None and base is not None else None
    return conv, base, span_a, span_b


def vwap(
    high: np.ndarray, low: np.ndarray, close: np.ndarray, volume: np.ndarray, w: int = 20
) -> float | None:
    if len(close) < 1 or volume is None:
        return None
    w = min(w, len(close))
    typical = (high[-w:] + low[-w:] + close[-w:]) / 3
    vol = volume[-w:]
    denom = np.sum(vol)
    return float(np.sum(typical * vol) / denom) if denom > 0 else None


def obv_series(close: np.ndarray, volume: np.ndarray) -> np.ndarray:
    obv = np.zeros(len(close))
    for i in range(1, len(close)):
        if close[i] > close[i - 1]:
            obv[i] = obv[i - 1] + volume[i]
        elif close[i] < close[i - 1]:
            obv[i] = obv[i - 1] - volume[i]
        else:
            obv[i] = obv[i - 1]
    return obv


def mfi(
    high: np.ndarray, low: np.ndarray, close: np.ndarray, volume: np.ndarray, n: int = 14
) -> float | None:
    if len(close) < n + 1 or volume is None:
        return None
    typical = (high + low + close) / 3
    raw_flow = typical * volume
    pos = np.zeros(len(close))
    neg = np.zeros(len(close))
    for i in range(1, len(close)):
        if typical[i] > typical[i - 1]:
            pos[i] = raw_flow[i]
        elif typical[i] < typical[i - 1]:
            neg[i] = raw_flow[i]
    pos_sum = np.sum(pos[-n:])
    neg_sum = np.sum(neg[-n:])
    if neg_sum == 0:
        return 100.0
    ratio = pos_sum / neg_sum
    return float(100 - 100 / (1 + ratio))


def _last(arr: np.ndarray) -> float | None:
    if len(arr) == 0 or np.isnan(arr[-1]):
        return None
    return float(arr[-1])


def compute_indicators(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray | None = None,
) -> IndicatorSet:
    ind = IndicatorSet()
    n = len(close)
    if n == 0:
        return ind
    if volume is None:
        volume = np.zeros(n)

    ind.last_close = float(close[-1])
    ind.sma_20, ind.sma_50, ind.sma_200 = sma(close, 20), sma(close, 50), sma(close, 200)
    ind.ema_12, ind.ema_26, ind.ema_50 = ema(close, 12), ema(close, 26), ema(close, 50)
    ind.rsi_14 = rsi(close, 14)
    ind.macd, ind.macd_signal, ind.macd_hist = macd(close)
    ind.adx_14, plus_di, minus_di = adx(high, low, close, 14)
    ind.atr_14 = atr(high, low, close, 14)
    ind.supertrend, ind.supertrend_dir = supertrend(high, low, close)
    ind.ichimoku_conversion, ind.ichimoku_base, ind.ichimoku_span_a, ind.ichimoku_span_b = (
        ichimoku(high, low)
    )
    ind.vwap = vwap(high, low, close, volume)
    obv = obv_series(close, volume)
    ind.obv = float(obv[-1])
    ind.obv_rising = bool(obv[-1] > obv[-21]) if n >= 21 else None
    ind.mfi_14 = mfi(high, low, close, volume, 14)

    if ind.sma_20 is not None:
        std = float(np.std(close[-20:]))
        ind.bb_middle = ind.sma_20
        ind.bb_upper = ind.sma_20 + 2 * std
        ind.bb_lower = ind.sma_20 - 2 * std
    if ind.ema_26 is not None and ind.atr_14 is not None and n >= 20:
        mid = ema(close, 20)
        if mid is not None:
            ind.keltner_upper = mid + 2 * ind.atr_14
            ind.keltner_lower = mid - 2 * ind.atr_14
    if n >= 20:
        ind.donchian_upper = float(np.max(high[-20:]))
        ind.donchian_lower = float(np.min(low[-20:]))

    window_52w = min(TRADING_DAYS, n)
    ind.high_52w = float(np.max(high[-window_52w:]))
    ind.low_52w = float(np.min(low[-window_52w:]))
    ind.pct_from_52w_high = (
        (close[-1] - ind.high_52w) / ind.high_52w if ind.high_52w else None
    )

    # Signed trend strength: ADX magnitude with directional sign.
    if ind.adx_14 is not None and plus_di is not None and minus_di is not None:
        ind.trend_strength = ind.adx_14 if plus_di >= minus_di else -ind.adx_14

    lookback = min(63, n - 1)
    if lookback > 0 and close[-lookback - 1] != 0:
        ind.momentum = float(close[-1] / close[-lookback - 1] - 1)

    if n >= 21:
        rets = np.diff(close[-21:]) / close[-21:-1]
        ind.volatility = float(np.std(rets) * np.sqrt(TRADING_DAYS))

    if ind.atr_14 and n >= 21:
        donchian_prev = float(np.max(high[-21:-1]))
        ind.breakout_strength = float((close[-1] - donchian_prev) / ind.atr_14)

    return ind
