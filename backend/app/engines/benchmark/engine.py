"""Market Benchmark Engine — the reusable scoring backbone.

Turns a raw metric value into a 0..1 quality sub-score by blending three references:

  * 40%  Country benchmark   (market-specific good/great band)
  * 30%  Industry benchmark  (the metric's median across the same sector)
  * 30%  Company history      (the company's own historical median for the metric)

Legs with no data drop out and the remaining weights renormalise. Direction (higher-
vs lower-is-better) comes from the profile. Designed to back any scoring model
(Pabrai now; Piotroski / Greenblatt / Buffett later) without duplicating logic.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.engines.benchmark.profiles import (
    METRIC_DIRECTION,
    country_profile,
    sector_adjust,
)

# Blend weights (configurable).
W_COUNTRY, W_INDUSTRY, W_HISTORY = 0.40, 0.30, 0.30


@dataclass(slots=True)
class MetricScore:
    metric: str
    value: float | None
    score: float | None          # 0..1, coverage-weighted across available legs
    country_band: tuple[float, float] | None = None
    industry_median: float | None = None
    company_median: float | None = None
    legs: dict[str, float] = field(default_factory=dict)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _band_score(value: float, good: float, great: float, higher: bool) -> float:
    """Ramp a value across a (good, great) band → 0..1 (0.6 at 'good', 1.0 at 'great')."""
    if higher:
        if value >= great:
            return 1.0
        if value >= good:
            return 0.6 + 0.4 * (value - good) / (great - good) if great != good else 0.8
        floor = max(good * 0.4, 0.0)
        return _clamp01(0.6 * (value - floor) / (good - floor)) if good != floor else 0.0
    # lower-is-better
    if value <= great:
        return 1.0
    if value <= good:
        return 0.6 + 0.4 * (good - value) / (good - great) if good != great else 0.8
    ceil = good * 2.0
    return _clamp01(0.6 * (ceil - value) / (ceil - good)) if ceil != good else 0.0


def _relative_score(value: float, median: float, higher: bool) -> float:
    """Smooth 0..1 comparison of a value to a reference median (0.5 == at median)."""
    denom = abs(median) + 1e-9
    z = (value - median) / denom
    s = 0.5 + 0.5 * math.tanh(1.5 * z)
    return s if higher else 1.0 - s


def score_metric(
    metric: str,
    value: float | None,
    region: str | None,
    sector: str | None,
    industry: str | None,
    industry_median: float | None = None,
    company_history: list[float] | None = None,
) -> MetricScore:
    if value is None:
        return MetricScore(metric, None, None)

    higher = METRIC_DIRECTION.get(metric, "higher") == "higher"
    legs: dict[str, float] = {}
    weights: dict[str, float] = {}

    band = country_profile(region).get(metric)
    adj_band = sector_adjust(band, metric, sector, industry) if band else None
    if adj_band is not None:
        legs["country"] = _band_score(value, adj_band[0], adj_band[1], higher)
        weights["country"] = W_COUNTRY

    if industry_median is not None:
        legs["industry"] = _relative_score(value, industry_median, higher)
        weights["industry"] = W_INDUSTRY

    hist = [h for h in (company_history or []) if h is not None]
    if len(hist) >= 3:
        med = sorted(hist)[len(hist) // 2]
        legs["history"] = _relative_score(value, med, higher)
        weights["history"] = W_HISTORY
    else:
        med = None

    if not weights:
        return MetricScore(metric, value, None, adj_band, industry_median, med, legs)

    total = sum(weights.values())
    score = sum(legs[k] * weights[k] for k in weights) / total
    return MetricScore(metric, value, _clamp01(score), adj_band, industry_median, med, legs)
