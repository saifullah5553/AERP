"""Weighted, explainable 0–100 technical score.

Directional trend/momentum/volume signals are each mapped to a 0–100 sub-score and
combined by weight, with the same renormalise-over-available-data + coverage +
per-metric-breakdown approach as the fundamental engine. A strong *down*-trend
scores low: booleans encode direction, not just presence.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.engines.common import clamp


def _higher_better(low: float, high: float) -> Callable[[float], float]:
    return lambda v: clamp((v - low) / (high - low) * 100.0)


def _band(
    ideal_lo: float, ideal_hi: float, hard_lo: float, hard_hi: float
) -> Callable[[float], float]:
    def scorer(v: float) -> float:
        if ideal_lo <= v <= ideal_hi:
            return 100.0
        if v < ideal_lo:
            return clamp((v - hard_lo) / (ideal_lo - hard_lo) * 100.0)
        return clamp((hard_hi - v) / (hard_hi - ideal_hi) * 100.0)

    return scorer


def _boolean(v: float) -> float:
    return 100.0 if v >= 0.5 else 0.0


@dataclass(frozen=True, slots=True)
class MetricSpec:
    key: str
    weight: float
    scorer: Callable[[float], float]
    label: str


# Weights sum to 1.0.
METRIC_SPECS: list[MetricSpec] = [
    # Trend (0.38)
    MetricSpec("above_sma50", 0.12, _boolean, "Price > 50-day SMA"),
    MetricSpec("above_sma200", 0.10, _boolean, "Price > 200-day SMA"),
    MetricSpec("golden_cross", 0.08, _boolean, "50-day > 200-day SMA"),
    MetricSpec("supertrend", 0.08, _boolean, "SuperTrend bullish"),
    # Momentum (0.30)
    MetricSpec("macd_hist_norm", 0.10, _higher_better(-0.02, 0.02), "MACD histogram"),
    MetricSpec("rsi", 0.10, _band(50, 70, 30, 90), "RSI(14)"),
    MetricSpec("momentum", 0.10, _higher_better(-0.15, 0.15), "3-month momentum"),
    # Strength / position (0.14)
    MetricSpec("adx", 0.08, _higher_better(15, 40), "ADX(14) trend strength"),
    MetricSpec("pct_from_52w_high", 0.06, _higher_better(-0.5, 0.0), "Proximity to 52w high"),
    # Volume / flow (0.18)
    MetricSpec("above_vwap", 0.06, _boolean, "Price > VWAP"),
    MetricSpec("obv_trend", 0.06, _boolean, "OBV rising"),
    MetricSpec("mfi", 0.06, _band(50, 80, 20, 90), "Money Flow Index"),
]

TOTAL_WEIGHT = sum(s.weight for s in METRIC_SPECS)
MIN_COVERAGE = 0.20


@dataclass(slots=True)
class TechnicalScore:
    score: float | None
    coverage: float
    breakdown: dict[str, Any]


def score_technical(metrics: dict[str, float | None]) -> TechnicalScore:
    present: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    weighted_sum = 0.0
    weight_present = 0.0

    for spec in METRIC_SPECS:
        value = metrics.get(spec.key)
        if value is None:
            missing.append(spec.key)
            continue
        sub = round(spec.scorer(float(value)), 2)
        contribution = sub * spec.weight
        weighted_sum += contribution
        weight_present += spec.weight
        present[spec.key] = {
            "label": spec.label,
            "value": round(float(value), 6),
            "sub_score": sub,
            "weight": spec.weight,
            "contribution": round(contribution, 4),
        }

    coverage = weight_present / TOTAL_WEIGHT if TOTAL_WEIGHT else 0.0
    if weight_present == 0.0 or coverage < MIN_COVERAGE:
        return TechnicalScore(
            score=None,
            coverage=round(coverage, 4),
            breakdown={
                "reason": "insufficient_price_history",
                "coverage": round(coverage, 4),
                "metrics": present,
                "missing": missing,
            },
        )

    score = round(weighted_sum / weight_present, 2)
    return TechnicalScore(
        score=score,
        coverage=round(coverage, 4),
        breakdown={
            "score": score,
            "coverage": round(coverage, 4),
            "weight_present": round(weight_present, 4),
            "metrics": present,
            "missing": missing,
        },
    )
