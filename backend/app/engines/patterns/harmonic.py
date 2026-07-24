"""Harmonic-pattern detection (Gartley, Bat, Butterfly, Crab, ABCD).

Matches the last five swing pivots (X, A, B, C, D) against each pattern's
Fibonacci-ratio template with tolerance. A pattern is emitted only when every
required leg ratio falls in range; confidence reflects how tightly the pivot D
matches the pattern's completion ratio.
"""

from __future__ import annotations

import numpy as np

from app.engines.patterns.base import PatternHit, clamp01
from app.engines.patterns.pivots import alternating, find_pivots
from app.models.enums import PatternCategory, PatternDirection

HM = PatternCategory.HARMONIC


# name: (ab_range, bc_range, cd_range, ad_range) as fractions of the prior leg;
# ad_range is D's retracement/extension of XA.
_SPECS: dict[str, tuple[tuple, tuple, tuple, tuple]] = {
    "gartley":   ((0.55, 0.68), (0.38, 0.89), (1.13, 1.62), (0.74, 0.83)),
    "bat":       ((0.38, 0.50), (0.38, 0.89), (1.60, 2.62), (0.85, 0.92)),
    "butterfly": ((0.72, 0.83), (0.38, 0.89), (1.60, 2.24), (1.24, 1.62)),
    "crab":      ((0.38, 0.62), (0.38, 0.89), (2.20, 3.62), (1.55, 1.68)),
}


def _in(value: float, rng: tuple[float, float]) -> bool:
    return rng[0] <= value <= rng[1]


def _closeness(value: float, rng: tuple[float, float]) -> float:
    center = (rng[0] + rng[1]) / 2
    half = (rng[1] - rng[0]) / 2 or 1e-9
    return clamp01(1 - abs(value - center) / half)


def detect_harmonic_patterns(
    high: np.ndarray, low: np.ndarray, close: np.ndarray, k: int = 3
) -> list[PatternHit]:
    if len(close) < 30:
        return []
    pivots = alternating(find_pivots(high, low, k))
    if len(pivots) < 5:
        return []
    x, a, b, c, d = pivots[-5:]

    xa = abs(a.price - x.price)
    ab = abs(b.price - a.price)
    bc = abs(c.price - b.price)
    cd = abs(d.price - c.price)
    if min(xa, ab, bc) == 0:
        return []

    r_ab = ab / xa
    r_bc = bc / ab
    r_cd = cd / bc
    # D as a retracement/extension of the whole XA leg, measured from A.
    r_ad = abs(a.price - d.price) / xa
    direction = PatternDirection.BULLISH if d.kind == "L" else PatternDirection.BEARISH

    hits: list[PatternHit] = []
    for name, (ab_r, bc_r, cd_r, ad_r) in _SPECS.items():
        if _in(r_ab, ab_r) and _in(r_bc, bc_r) and _in(r_cd, cd_r) and _in(r_ad, ad_r):
            conf = 0.5 + 0.35 * (
                _closeness(r_ab, ab_r) + _closeness(r_ad, ad_r)
            ) / 2
            hits.append(PatternHit(
                name, HM, direction, round(clamp01(conf), 3), x.index,
                breakout_level=float(c.price), target_price=float(a.price),
                stop_level=float(x.price),
            ))

    # ABCD: AB and CD comparable, BC a 0.618–0.786 retrace, CD a 1.27–1.618 ext.
    if _in(r_bc, (0.60, 0.80)) and _in(r_cd, (1.20, 1.65)):
        conf = 0.5 + 0.3 * _closeness(r_cd, (1.20, 1.65))
        hits.append(PatternHit(
            "abcd", HM, direction, round(clamp01(conf), 3), a.index,
            breakout_level=float(c.price), target_price=float(d.price),
            stop_level=float(a.price),
        ))
    return hits
