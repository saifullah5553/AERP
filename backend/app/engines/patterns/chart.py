"""Classic chart-pattern detection from swing pivots and trendline fits.

Covers double top/bottom, head & shoulders (+ inverse), the triangle family,
rectangles, flags, and cup & handle. Each detector returns a real geometric match
with confidence and, where applicable, breakout/target/stop levels.
"""

from __future__ import annotations

import numpy as np

from app.engines.patterns.base import PatternHit, clamp01
from app.engines.patterns.pivots import Pivot, alternating, find_pivots
from app.models.enums import PatternCategory, PatternDirection

CH = PatternCategory.CHART
BULL = PatternDirection.BULLISH
BEAR = PatternDirection.BEARISH
NEUTRAL = PatternDirection.NEUTRAL


def _pct(a: float, b: float) -> float:
    mid = (a + b) / 2
    return abs(a - b) / mid if mid else 1.0


def _rel_slope(xs: list[int], ys: list[float]) -> float:
    """Slope per bar, normalised by mean price (so it's comparable across names)."""
    if len(xs) < 2:
        return 0.0
    slope = float(np.polyfit(xs, ys, 1)[0])
    mean = float(np.mean(ys)) or 1.0
    return slope / mean


def detect_chart_patterns(
    high: np.ndarray, low: np.ndarray, close: np.ndarray, k: int = 3
) -> list[PatternHit]:
    n = len(close)
    if n < 30:
        return []
    hits: list[PatternHit] = []
    pivots = alternating(find_pivots(high, low, k))

    hits += _double(pivots, high, low, close)
    hits += _head_and_shoulders(pivots)
    hits += _triangle_family(pivots, high, low, close)
    hits += _flag(close, high, low)
    hits += _cup_and_handle(close)
    return hits


# Double top/bottom geometry thresholds. Kept strict on purpose: two similar
# extremes alone are common noise — a real double top/bottom needs a *deep* valley
# between the peaks, the peaks near the recent extreme, enough time separation, and
# price rolling back through the neckline. These gates remove false positives like
# two minor bumps mid-trend.
_PEAK_SIMILARITY = 0.03   # the two peaks must be within 3% of each other
_MIN_VALLEY_DEPTH = 0.05  # the middle trough must be ≥5% away from the lower peak
_MIN_SEPARATION = 8       # bars between the two peaks
_PROMINENCE = 0.985       # peaks must sit within ~1.5% of the extreme since peak 1


def _double(
    pivots: list[Pivot], high: np.ndarray, low: np.ndarray, close: np.ndarray
) -> list[PatternHit]:
    if len(pivots) < 3:
        return []
    p3, p2, p1 = pivots[-1], pivots[-2], pivots[-3]
    hits: list[PatternHit] = []
    n = len(close)
    last = float(close[-1])
    sep = abs(p3.index - p1.index)
    if sep < _MIN_SEPARATION:
        return hits

    # ── Double top: H, L, H — two similar peaks with a deep valley, near the high ──
    if p1.kind == "H" and p2.kind == "L" and p3.kind == "H":
        peak_sim = _pct(p1.price, p3.price)
        lower_peak = min(p1.price, p3.price)
        valley_depth = (lower_peak - p2.price) / lower_peak if lower_peak else 0.0
        seg_high = float(np.max(high[p1.index:])) if p1.index < n else lower_peak
        prominent = max(p1.price, p3.price) >= _PROMINENCE * seg_high
        confirmed = last < p2.price  # neckline (valley) broken to the downside
        if peak_sim < _PEAK_SIMILARITY and valley_depth >= _MIN_VALLEY_DEPTH and prominent:
            base = 0.75 if confirmed else 0.55
            conf = clamp01(base + valley_depth - peak_sim * 8)
            height = max(p1.price, p3.price) - p2.price
            hits.append(PatternHit(
                "double_top", CH, BEAR, conf, p1.index,
                breakout_level=p2.price, target_price=p2.price - height,
                stop_level=max(p1.price, p3.price),
            ))

    # ── Double bottom: L, H, L — two similar troughs with a high peak, near the low ─
    if p1.kind == "L" and p2.kind == "H" and p3.kind == "L":
        trough_sim = _pct(p1.price, p3.price)
        higher_trough = max(p1.price, p3.price)
        peak_height = (p2.price - higher_trough) / higher_trough if higher_trough else 0.0
        seg_low = float(np.min(low[p1.index:])) if p1.index < n else higher_trough
        prominent = min(p1.price, p3.price) <= seg_low / _PROMINENCE
        confirmed = last > p2.price  # neckline (peak) broken to the upside
        if trough_sim < _PEAK_SIMILARITY and peak_height >= _MIN_VALLEY_DEPTH and prominent:
            base = 0.75 if confirmed else 0.55
            conf = clamp01(base + peak_height - trough_sim * 8)
            height = p2.price - min(p1.price, p3.price)
            hits.append(PatternHit(
                "double_bottom", CH, BULL, conf, p1.index,
                breakout_level=p2.price, target_price=p2.price + height,
                stop_level=min(p1.price, p3.price),
            ))
    return hits


def _head_and_shoulders(pivots: list[Pivot]) -> list[PatternHit]:
    if len(pivots) < 5:
        return []
    a, b, c, d, e = pivots[-5:]
    hits: list[PatternHit] = []
    kinds = [p.kind for p in (a, b, c, d, e)]
    neckline = (b.price + d.price) / 2
    conf = clamp01(0.75 - _pct(a.price, e.price) * 8)

    # H, L, H, L, H with middle highest and similar shoulders.
    if (
        kinds == ["H", "L", "H", "L", "H"]
        and c.price > a.price and c.price > e.price and _pct(a.price, e.price) < 0.03
    ):
        hits.append(PatternHit(
            "head_and_shoulders", CH, BEAR, conf, a.index,
            breakout_level=neckline, target_price=neckline - (c.price - neckline),
            stop_level=c.price,
        ))
    # L, H, L, H, L inverse (middle lowest).
    if (
        kinds == ["L", "H", "L", "H", "L"]
        and c.price < a.price and c.price < e.price and _pct(a.price, e.price) < 0.03
    ):
        hits.append(PatternHit(
            "inverse_head_and_shoulders", CH, BULL, conf, a.index,
            breakout_level=neckline, target_price=neckline + (neckline - c.price),
            stop_level=c.price,
        ))
    return hits


def _triangle_family(
    pivots: list[Pivot], high: np.ndarray, low: np.ndarray, close: np.ndarray
) -> list[PatternHit]:
    highs = [p for p in pivots if p.kind == "H"][-3:]
    lows = [p for p in pivots if p.kind == "L"][-3:]
    if len(highs) < 2 or len(lows) < 2:
        return []
    sh = _rel_slope([p.index for p in highs], [p.price for p in highs])
    sl = _rel_slope([p.index for p in lows], [p.price for p in lows])
    flat = 0.0006  # per-bar relative slope treated as horizontal

    res = float(np.mean([p.price for p in highs]))
    sup = float(np.mean([p.price for p in lows]))
    height = res - sup
    last = float(close[-1])

    if abs(sh) < flat and sl > flat:
        return [PatternHit("ascending_triangle", CH, BULL, 0.65, highs[0].index,
                           breakout_level=res, target_price=res + height, stop_level=sup)]
    if sh < -flat and abs(sl) < flat:
        return [PatternHit("descending_triangle", CH, BEAR, 0.65, highs[0].index,
                           breakout_level=sup, target_price=sup - height, stop_level=res)]
    if sh < -flat and sl > flat:
        direction = BULL if last > (res + sup) / 2 else BEAR
        return [PatternHit("symmetrical_triangle", CH, direction, 0.6, highs[0].index,
                           breakout_level=res if direction == BULL else sup)]
    if abs(sh) < flat and abs(sl) < flat and height > 0:
        return [PatternHit("rectangle", CH, NEUTRAL, 0.55, highs[0].index,
                           breakout_level=res, stop_level=sup)]
    return []


def _flag(close: np.ndarray, high: np.ndarray, low: np.ndarray) -> list[PatternHit]:
    n = len(close)
    if n < 25:
        return []
    pole = close[-20:-10]
    flag = close[-10:]
    pole_ret = (pole[-1] - pole[0]) / pole[0] if pole[0] else 0.0
    flag_slope = _rel_slope(list(range(len(flag))), list(flag))

    if pole_ret > 0.08 and flag_slope <= 0.0:  # sharp rise then drift down/sideways
        breakout = float(np.max(high[-10:]))
        target = breakout + (pole[-1] - pole[0])
        return [PatternHit("bull_flag", CH, BULL, clamp01(0.55 + pole_ret), n - 20,
                           breakout_level=breakout, target_price=target,
                           stop_level=float(np.min(low[-10:])))]
    if pole_ret < -0.08 and flag_slope >= 0.0:
        breakout = float(np.min(low[-10:]))
        target = breakout + (pole[-1] - pole[0])
        return [PatternHit("bear_flag", CH, BEAR, clamp01(0.55 - pole_ret), n - 20,
                           breakout_level=breakout, target_price=target,
                           stop_level=float(np.max(high[-10:])))]
    return []


def _cup_and_handle(close: np.ndarray) -> list[PatternHit]:
    n = len(close)
    if n < 40:
        return []
    window = close[-40:]
    cup = window[:28]
    handle = window[28:]
    rim_left = float(cup[0])
    rim_right = float(cup[-1])
    cup_low = float(np.min(cup))
    depth = ((rim_left + rim_right) / 2) - cup_low
    if depth <= 0:
        return []
    handle_low = float(np.min(handle))
    handle_pullback = rim_right - handle_low

    # Rounded bottom: rims roughly level, low near the middle, shallow handle.
    low_idx = int(np.argmin(cup))
    centered = 0.3 * len(cup) < low_idx < 0.7 * len(cup)
    if _pct(rim_left, rim_right) < 0.05 and centered and 0 < handle_pullback < depth / 2:
        breakout = max(rim_left, rim_right)
        return [PatternHit("cup_and_handle", CH, BULL, 0.62, n - 40,
                           breakout_level=breakout, target_price=breakout + depth,
                           stop_level=handle_low)]
    return []
