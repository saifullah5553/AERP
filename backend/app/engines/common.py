"""Shared numeric helpers for the analytics engines.

All engine math funnels through these so that missing data (``None``) and
division-by-zero degrade to ``None`` instead of raising — the engines never
fabricate a value to fill a gap.
"""

from __future__ import annotations

from decimal import Decimal


def f(value: object) -> float | None:
    """Coerce DB ``Numeric`` (Decimal), int, or float to float; pass through None."""
    if value is None:
        return None
    if isinstance(value, float | int | Decimal):
        return float(value)
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def safe_div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def growth(current: float | None, previous: float | None) -> float | None:
    """Period-over-period growth as a fraction (0.10 == +10%)."""
    if current is None or previous is None or previous == 0:
        return None
    return (current - previous) / abs(previous)


def cagr(first: float | None, last: float | None, years: float) -> float | None:
    """Compound annual growth rate over ``years``. Requires positive endpoints."""
    if first is None or last is None or years <= 0 or first <= 0 or last <= 0:
        return None
    return (last / first) ** (1.0 / years) - 1.0


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))
