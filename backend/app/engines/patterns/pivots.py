"""Swing-pivot detection (fractals).

Chart and harmonic patterns are built from swing highs/lows rather than raw bars,
which is what makes detection robust to noise. A bar ``i`` is a pivot high if its
high is the maximum of the ``[i-k, i+k]`` window (and symmetrically for lows).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(slots=True)
class Pivot:
    index: int
    price: float
    kind: str  # "H" (high) or "L" (low)


def find_pivots(high: np.ndarray, low: np.ndarray, k: int = 3) -> list[Pivot]:
    """Return swing pivots in chronological order, alternating-ish by nature."""
    n = len(high)
    pivots: list[Pivot] = []
    for i in range(k, n - k):
        window_h = high[i - k : i + k + 1]
        window_l = low[i - k : i + k + 1]
        if high[i] == window_h.max() and (high[i] > high[i - 1] or high[i] > high[i + 1]):
            pivots.append(Pivot(i, float(high[i]), "H"))
        elif low[i] == window_l.min() and (low[i] < low[i - 1] or low[i] < low[i + 1]):
            pivots.append(Pivot(i, float(low[i]), "L"))
    return pivots


def alternating(pivots: list[Pivot]) -> list[Pivot]:
    """Collapse consecutive same-kind pivots, keeping the more extreme one.

    Produces a clean zig-zag (…H, L, H, L…) suitable for chart/harmonic matching.
    """
    out: list[Pivot] = []
    for p in pivots:
        if out and out[-1].kind == p.kind:
            prev = out[-1]
            keep = (
                p if (p.kind == "H" and p.price >= prev.price) else
                p if (p.kind == "L" and p.price <= prev.price) else prev
            )
            out[-1] = keep
        else:
            out.append(p)
    return out
