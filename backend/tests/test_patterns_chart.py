from __future__ import annotations

import numpy as np
from app.engines.patterns.chart import detect_chart_patterns
from app.engines.patterns.pivots import alternating, find_pivots


def _legs(prices: list[float], per: int = 8) -> np.ndarray:
    """Build a piecewise-linear close series through the given vertex prices."""
    out: list[float] = []
    for i in range(len(prices) - 1):
        seg = np.linspace(prices[i], prices[i + 1], per, endpoint=False)
        out.extend(seg.tolist())
    out.append(prices[-1])
    return np.array(out)


def test_pivots_zigzag() -> None:
    close = np.array([1, 3, 2, 5, 1, 6, 2], dtype=float)
    pivots = find_pivots(close, close, k=1)
    kinds = [p.kind for p in pivots]
    assert kinds == ["H", "L", "H", "L", "H"]
    assert alternating(pivots) == pivots  # already alternating


def test_double_bottom() -> None:
    close = _legs([110, 80, 95, 81, 95])   # down, up, down (~same low), up
    high, low = close + 0.5, close - 0.5
    names = {h.name for h in detect_chart_patterns(high, low, close, k=3)}
    assert "double_bottom" in names


def test_double_top() -> None:
    close = _legs([90, 120, 105, 119, 105])
    high, low = close + 0.5, close - 0.5
    names = {h.name for h in detect_chart_patterns(high, low, close, k=3)}
    assert "double_top" in names


def test_double_bottom_levels_are_sane() -> None:
    close = _legs([110, 80, 95, 81, 95])
    high, low = close + 0.5, close - 0.5
    hit = next(h for h in detect_chart_patterns(high, low, close, k=3) if h.name == "double_bottom")
    assert hit.breakout_level > hit.stop_level
    assert hit.target_price > hit.breakout_level  # measured move up
    assert 0.0 < hit.confidence <= 1.0


def test_too_short_returns_empty() -> None:
    close = np.linspace(100, 110, 10)
    assert detect_chart_patterns(close + 0.5, close - 0.5, close) == []
