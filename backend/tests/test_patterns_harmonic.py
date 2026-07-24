from __future__ import annotations

import numpy as np
from app.engines.patterns.harmonic import detect_harmonic_patterns
from app.models.enums import PatternDirection


def _legs(prices: list[float], per: int = 6) -> np.ndarray:
    out: list[float] = []
    for i in range(len(prices) - 1):
        out.extend(np.linspace(prices[i], prices[i + 1], per, endpoint=False).tolist())
    out.append(prices[-1])
    return np.array(out)


def test_gartley_detected() -> None:
    # Bullish Gartley: AB=0.618 XA, BC=0.5 AB, D at the 0.786 XA retracement.
    x, a = 100.0, 120.0                       # XA = +20
    b = a - 0.618 * (a - x)                   # 107.64
    c = b + 0.5 * (a - b)                     # 113.82
    d = a - 0.786 * (a - x)                   # 104.28 → |A-D|/XA = 0.786
    # Lead-in so X (a low) is an internal pivot; bounce up after D so D is a pivot low.
    close = _legs([112.0, x, a, b, c, d, 115.0])
    high, low = close + 0.3, close - 0.3

    hits = detect_harmonic_patterns(high, low, close, k=3)
    names = {h.name for h in hits}
    assert "gartley" in names
    gartley = next(h for h in hits if h.name == "gartley")
    assert gartley.direction == PatternDirection.BULLISH
    assert 0.0 < gartley.confidence <= 1.0


def test_no_pattern_on_trend() -> None:
    close = np.linspace(100, 130, 40)
    assert detect_harmonic_patterns(close + 0.3, close - 0.3, close) == []
