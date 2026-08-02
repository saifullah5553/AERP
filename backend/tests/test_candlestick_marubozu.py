from __future__ import annotations

import numpy as np
from app.engines.patterns.candlestick import detect_candlesticks


def _bars(last: tuple[float, float, float, float]) -> tuple[np.ndarray, ...]:
    """Three flat leading bars plus the bar under test (detectors read the last bar)."""
    o = [100.0, 100.0, 100.0, last[0]]
    h = [101.0, 101.0, 101.0, last[1]]
    low = [99.0, 99.0, 99.0, last[2]]
    c = [100.0, 100.0, 100.0, last[3]]
    return (np.array(o), np.array(h), np.array(low), np.array(c))


def _names(last: tuple[float, float, float, float]) -> set[str]:
    return {p.name for p in detect_candlesticks(*_bars(last))}


def test_bearish_opening_marubozu_is_detected() -> None:
    # Real INCY bar, 2026-07-31: opens exactly at the high and sells off all day. Body is only
    # ~75% of the range, so the full-marubozu rule (>=90%) misses it - this variant exists
    # precisely for that case.
    assert "bearish_opening_marubozu" in _names((122.75, 122.75, 118.44, 119.52))


def test_bullish_opening_marubozu_is_detected() -> None:
    # Mirror image: opens at the low and rallies, leaving an upper shadow only.
    assert "bullish_opening_marubozu" in _names((100.0, 106.0, 100.0, 104.5))


def test_bearish_closing_marubozu_is_detected() -> None:
    # Closes exactly on the low, with an upper shadow above the open.
    assert "bearish_closing_marubozu" in _names((104.0, 106.0, 100.0, 100.0))


def test_full_marubozu_still_wins_over_the_variants() -> None:
    # No shadow at either end stays the plain marubozu, not an opening/closing one.
    names = _names((106.0, 106.0, 100.0, 100.0))
    assert "bearish_marubozu" in names
    assert "bearish_opening_marubozu" not in names


def test_small_body_is_not_a_marubozu() -> None:
    # A stubby body sitting at the top of its range is not a marubozu at any tolerance.
    assert not {n for n in _names((101.0, 101.0, 95.0, 100.6)) if "marubozu" in n}
