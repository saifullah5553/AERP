"""Shared types for the pattern-detection engine.

A :class:`PatternHit` is a single detected pattern with a 0–1 confidence and,
where meaningful, the trade levels a chart overlay needs (breakout, target, stop).
Detectors return real geometric findings — nothing is emitted unless the shape
criteria are met.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.enums import PatternCategory, PatternDirection


@dataclass(slots=True)
class PatternHit:
    name: str                       # snake_case, e.g. "cup_and_handle"
    category: PatternCategory
    direction: PatternDirection
    confidence: float               # 0..1
    start_index: int | None = None  # index into the analysed window
    breakout_level: float | None = None
    target_price: float | None = None
    stop_level: float | None = None


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))
