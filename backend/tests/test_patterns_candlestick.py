from __future__ import annotations

import numpy as np
from app.engines.patterns.candlestick import detect_candlesticks
from app.models.enums import PatternDirection


def _names(hits):
    return {h.name for h in hits}


def _flat(n, price=100.0):
    o = np.full(n, price)
    c = np.full(n, price)
    h = np.full(n, price + 0.5)
    low = np.full(n, price - 0.5)
    return o, h, low, c


def test_doji() -> None:
    o, h, low, c = _flat(10)
    o[-1], c[-1], h[-1], low[-1] = 100.0, 100.05, 101.0, 99.0
    assert "doji" in _names(detect_candlesticks(o, h, low, c))


def test_hammer_in_downtrend() -> None:
    # Descending context so the last-bar hammer reads bullish, not hanging man.
    c = np.linspace(110, 101, 10)
    o = c + 0.2
    h = c + 0.3
    low = c - 0.3
    o[-1], c[-1], h[-1], low[-1] = 100.0, 100.5, 100.6, 97.0
    hits = detect_candlesticks(o, h, low, c)
    hammer = next(x for x in hits if x.name == "hammer")
    assert hammer.direction == PatternDirection.BULLISH


def test_bullish_engulfing() -> None:
    o, h, low, c = _flat(10)
    o[-2], c[-2] = 101.0, 100.0          # bearish
    o[-1], c[-1] = 99.5, 101.5           # bullish body engulfs prior
    h[-1], low[-1] = 101.6, 99.4
    assert "bullish_engulfing" in _names(detect_candlesticks(o, h, low, c))


def test_three_white_soldiers() -> None:
    o, h, low, c = _flat(10)
    o[-3], c[-3] = 100.0, 101.0
    o[-2], c[-2] = 100.8, 102.0
    o[-1], c[-1] = 101.8, 103.0
    for j in (-3, -2, -1):
        h[j], low[j] = c[j] + 0.2, o[j] - 0.2
    assert "three_white_soldiers" in _names(detect_candlesticks(o, h, low, c))


def test_morning_star() -> None:
    o, h, low, c = _flat(10, price=100.0)
    o[-3], c[-3] = 110.0, 104.0          # big bearish
    o[-2], c[-2] = 103.6, 104.0          # small star
    o[-1], c[-1] = 104.0, 108.0          # big bullish, closes above midpoint
    for j in range(10):
        h[j] = max(o[j], c[j]) + 0.2
        low[j] = min(o[j], c[j]) - 0.2
    hits = detect_candlesticks(o, h, low, c)
    assert "morning_star" in _names(hits)


def test_needs_three_bars() -> None:
    o, h, low, c = _flat(2)
    assert detect_candlesticks(o, h, low, c) == []
