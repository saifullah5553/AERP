"""Pattern accuracy: textbook shapes must fire, near-misses must not.

Every case is built from the standard definition, and each positive is paired with a negative
that breaks exactly one requirement. A detector that only has positive tests will happily fire
on everything - which is the failure mode these patterns actually had.
"""

from __future__ import annotations

import numpy as np
from app.engines.patterns.candlestick import detect_candlesticks
from app.engines.patterns.chart import detect_chart_patterns


def _bars(rows: list[tuple[float, float, float, float]]):
    """rows of (open, high, low, close) -> the four arrays the detectors take."""
    o = np.array([r[0] for r in rows], dtype=float)
    h = np.array([r[1] for r in rows], dtype=float)
    low = np.array([r[2] for r in rows], dtype=float)
    c = np.array([r[3] for r in rows], dtype=float)
    return o, h, low, c


def _names(hits) -> set[str]:
    return {hit.name for hit in hits}


def _flat(n: int, price: float = 100.0):
    """A quiet run of small candles, for padding context."""
    return [(price, price + 0.4, price - 0.4, price) for _ in range(n)]


# ── single-bar ────────────────────────────────────────────────────────────────────────
def test_hammer_needs_a_long_lower_shadow_after_a_fall() -> None:
    falling = [(110 - i * 2, 110.5 - i * 2, 109 - i * 2, 109.5 - i * 2) for i in range(10)]
    hammer = (92.0, 92.5, 85.0, 92.2)          # tiny body, lower shadow ~24x it
    assert "hammer" in _names(detect_candlesticks(*_bars(falling + [hammer])))


def test_a_long_lower_shadow_in_an_uptrend_is_a_hanging_man_not_a_hammer() -> None:
    rising = [(90 + i * 2, 91 + i * 2, 89.5 + i * 2, 90.8 + i * 2) for i in range(10)]
    bar = (112.0, 112.5, 105.0, 112.2)
    names = _names(detect_candlesticks(*_bars(rising + [bar])))
    assert "hanging_man" in names
    assert "hammer" not in names


def test_a_bar_with_shadows_at_both_ends_is_not_a_hammer() -> None:
    falling = [(110 - i * 2, 110.5 - i * 2, 109 - i * 2, 109.5 - i * 2) for i in range(10)]
    # Long lower shadow, but an equally long upper one - that is a spinning top.
    both = (92.0, 99.0, 85.0, 92.2)
    assert "hammer" not in _names(detect_candlesticks(*_bars(falling + [both])))


def test_doji_requires_open_and_close_to_be_practically_equal() -> None:
    bars = _flat(10) + [(100.0, 103.0, 97.0, 100.05)]
    assert "doji" in _names(detect_candlesticks(*_bars(bars)))


def test_a_solid_body_is_not_a_doji() -> None:
    bars = _flat(10) + [(100.0, 103.0, 97.0, 102.0)]
    assert "doji" not in _names(detect_candlesticks(*_bars(bars)))


def test_marubozu_has_no_shadows() -> None:
    bars = _flat(10) + [(100.0, 110.0, 100.0, 110.0)]
    assert "bullish_marubozu" in _names(detect_candlesticks(*_bars(bars)))


# ── two-bar ───────────────────────────────────────────────────────────────────────────
def test_bullish_engulfing_swallows_the_previous_body() -> None:
    bars = _flat(10) + [(100.0, 100.5, 95.0, 96.0), (95.0, 101.5, 94.5, 101.0)]
    assert "bullish_engulfing" in _names(detect_candlesticks(*_bars(bars)))


def test_a_body_that_only_partly_covers_the_previous_one_is_not_engulfing() -> None:
    bars = _flat(10) + [(100.0, 100.5, 95.0, 96.0), (96.5, 99.5, 96.0, 99.0)]
    assert "bullish_engulfing" not in _names(detect_candlesticks(*_bars(bars)))


def test_engulfing_a_doji_is_not_an_engulfing_pattern() -> None:
    """The prior bar must have a real body. Swallowing a doji signals nothing."""
    bars = _flat(10) + [(100.0, 100.6, 99.4, 100.0), (99.0, 104.0, 98.5, 103.5)]
    assert "bullish_engulfing" not in _names(detect_candlesticks(*_bars(bars)))


# ── three-bar ─────────────────────────────────────────────────────────────────────────
def test_morning_star_is_a_gap_down_star_then_a_strong_recovery() -> None:
    falling = [(110 - i, 110.5 - i, 109 - i, 109.2 - i) for i in range(10)]
    bars = falling + [
        (100.0, 100.5, 92.0, 92.5),      # long bearish
        (91.0, 91.8, 90.2, 91.2),        # small star, gapped below
        (92.0, 99.0, 91.8, 98.5),        # strong bullish, closes above the midpoint
    ]
    assert "morning_star" in _names(detect_candlesticks(*_bars(bars)))


def test_a_feeble_third_bar_is_not_a_morning_star() -> None:
    """Closing barely above the star is not a recovery, whatever the first two bars did."""
    falling = [(110 - i, 110.5 - i, 109 - i, 109.2 - i) for i in range(10)]
    bars = falling + [
        (100.0, 100.5, 92.0, 92.5),
        (91.0, 91.8, 90.2, 91.2),
        (91.3, 91.9, 91.0, 91.6),        # tiny bullish bar, nowhere near the midpoint
    ]
    assert "morning_star" not in _names(detect_candlesticks(*_bars(bars)))


def test_three_white_soldiers_need_three_substantial_rising_bodies() -> None:
    bars = _flat(10) + [
        (100.0, 104.2, 99.8, 104.0),
        (103.0, 108.2, 102.8, 108.0),
        (107.0, 112.2, 106.8, 112.0),
    ]
    assert "three_white_soldiers" in _names(detect_candlesticks(*_bars(bars)))


def test_three_tiny_up_days_are_not_three_white_soldiers() -> None:
    """The loosest bug in the set: any three-day drift used to qualify."""
    bars = _flat(10) + [
        (100.0, 100.3, 99.9, 100.1),
        (100.1, 100.4, 100.0, 100.2),
        (100.2, 100.5, 100.1, 100.3),
    ]
    assert "three_white_soldiers" not in _names(detect_candlesticks(*_bars(bars)))


# ── chart patterns ────────────────────────────────────────────────────────────────────
def _series(points: list[float], per_leg: int = 6):
    """A price path through `points`, linearly interpolated, as OHLC arrays."""
    path: list[float] = []
    for a, b in zip(points, points[1:], strict=False):
        path += list(np.linspace(a, b, per_leg, endpoint=False))
    path.append(points[-1])
    close = np.array(path, dtype=float)
    return close * 0.999, close * 1.001, close * 0.998, close


def test_inverse_head_and_shoulders_needs_a_head_below_both_shoulders() -> None:
    _o, h, low, c = _series([100, 80, 95, 62, 95, 80.5, 105])
    assert "inverse_head_and_shoulders" in _names(detect_chart_patterns(h, low, c))


def test_a_flat_bottom_is_not_an_inverse_head_and_shoulders() -> None:
    """The head must be meaningfully lower. Three lows at the same level are a range.

    This is the false positive reported on 4001.SR: the detector asked only that the middle
    low be BELOW the other two, so a head a fraction of a percent lower qualified.
    """
    _o, h, low, c = _series([100, 80, 95, 79.6, 95, 80.0, 105])
    assert "inverse_head_and_shoulders" not in _names(detect_chart_patterns(h, low, c))


def test_a_steeply_sloping_neckline_is_not_a_head_and_shoulders() -> None:
    """The two peaks between the lows form the neckline; it cannot be a ramp."""
    _o, h, low, c = _series([100, 80, 88, 62, 112, 80.5, 130])
    assert "inverse_head_and_shoulders" not in _names(detect_chart_patterns(h, low, c))


def test_head_and_shoulders_tops_out_in_the_middle() -> None:
    _o, h, low, c = _series([60, 90, 70, 115, 70, 90.5, 55])
    assert "head_and_shoulders" in _names(detect_chart_patterns(h, low, c))


def test_uneven_shoulders_are_not_a_head_and_shoulders() -> None:
    _o, h, low, c = _series([60, 90, 70, 115, 70, 74.0, 55])
    assert "head_and_shoulders" not in _names(detect_chart_patterns(h, low, c))
