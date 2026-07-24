from __future__ import annotations

import numpy as np
import pytest
from app.engines.technical import indicators as ti


def _uptrend(n: int = 260, step: float = 0.5, base: float = 100.0):
    close = base + np.arange(n) * step
    high = close + 0.5
    low = close - 0.5
    volume = np.full(n, 1_000.0) + np.arange(n)  # rising volume
    return high, low, close, volume


def _downtrend(n: int = 260, step: float = 0.5, base: float = 300.0):
    close = base - np.arange(n) * step
    high = close + 0.5
    low = close - 0.5
    volume = np.full(n, 1_000.0)
    return high, low, close, volume


def test_sma_ema_of_constant_series() -> None:
    x = np.full(50, 42.0)
    assert ti.sma(x, 20) == pytest.approx(42.0)
    assert ti.ema(x, 20) == pytest.approx(42.0)


def test_short_series_returns_none() -> None:
    x = np.array([1.0, 2.0, 3.0])
    assert ti.sma(x, 20) is None
    assert ti.rsi(x, 14) is None
    assert ti.adx(x, x, x, 14) == (None, None, None)


def test_rsi_extremes() -> None:
    _, _, up, _ = _uptrend()
    _, _, down, _ = _downtrend()
    assert ti.rsi(up, 14) == pytest.approx(100.0)   # only gains
    assert ti.rsi(down, 14) == pytest.approx(0.0)    # only losses


def test_macd_sign_follows_trend() -> None:
    _, _, up, _ = _uptrend()
    _, _, down, _ = _downtrend()
    assert ti.macd(up)[0] > 0
    assert ti.macd(down)[0] < 0


def test_bollinger_from_indicatorset() -> None:
    high, low, close, volume = _uptrend()
    ind = ti.compute_indicators(high, low, close, volume)
    assert ind.bb_upper > ind.bb_middle > ind.bb_lower
    assert ind.donchian_upper >= ind.donchian_lower


def test_indicatorset_uptrend_signals() -> None:
    high, low, close, volume = _uptrend()
    ind = ti.compute_indicators(high, low, close, volume)
    assert ind.last_close == close[-1]
    assert ind.sma_50 > ind.sma_200          # golden cross
    assert ind.last_close > ind.sma_50       # above trend
    assert ind.supertrend_dir == 1           # bullish supertrend
    assert ind.momentum > 0
    assert ind.obv_rising is True
    assert ind.trend_strength is not None and ind.trend_strength > 0  # signed +
    assert ind.high_52w >= ind.last_close - 1


def test_indicatorset_downtrend_signals() -> None:
    high, low, close, volume = _downtrend()
    ind = ti.compute_indicators(high, low, close, volume)
    assert ind.last_close < ind.sma_50
    assert ind.supertrend_dir == -1
    assert ind.momentum < 0
    assert ind.trend_strength is not None and ind.trend_strength < 0  # signed -


def test_atr_positive() -> None:
    high, low, close, _ = _uptrend()
    assert ti.atr(high, low, close, 14) > 0
