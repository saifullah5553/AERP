"""Weighted, explainable 0–100 fundamental score.

Each quality/growth/health metric is mapped to a 0–100 sub-score through an
explicit rubric, then combined by weight. Metrics with no data are dropped and the
remaining weights are renormalised, so the score reflects only what is actually
known — and a ``coverage`` figure records how much that was. The full per-metric
breakdown is returned for storage, making every score auditable.

Valuation ratios (P/E, EV/EBITDA, …) are intentionally excluded here: they measure
*cheapness*, not *quality*, and feed the value/composite dimensions in Phase 6.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.engines.common import clamp


def _higher_better(low: float, high: float) -> Callable[[float], float]:
    return lambda v: clamp((v - low) / (high - low) * 100.0)


def _lower_better(low: float, high: float) -> Callable[[float], float]:
    return lambda v: clamp((high - v) / (high - low) * 100.0)


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


@dataclass(frozen=True, slots=True)
class MetricSpec:
    key: str
    weight: float
    scorer: Callable[[float], float]
    label: str


# Weights sum to 1.0. Grouped by theme for readability.
METRIC_SPECS: list[MetricSpec] = [
    # Profitability (0.38)
    MetricSpec("roe", 0.14, _higher_better(0.0, 0.25), "Return on equity"),
    MetricSpec("net_margin", 0.10, _higher_better(0.0, 0.20), "Net margin"),
    MetricSpec("roa", 0.08, _higher_better(0.0, 0.12), "Return on assets"),
    MetricSpec("gross_margin", 0.06, _higher_better(0.0, 0.60), "Gross margin"),
    # Growth (0.20)
    MetricSpec("revenue_growth", 0.10, _higher_better(-0.10, 0.25), "Revenue growth"),
    MetricSpec("eps_growth", 0.10, _higher_better(-0.10, 0.30), "EPS growth"),
    # Balance-sheet strength (0.22)
    MetricSpec("debt_to_equity", 0.10, _lower_better(0.0, 2.5), "Debt / equity"),
    MetricSpec("current_ratio", 0.06, _band(1.5, 3.0, 0.5, 6.0), "Current ratio"),
    MetricSpec("interest_coverage", 0.06, _higher_better(1.0, 10.0), "Interest coverage"),
    # Cash flow + composite health (0.20)
    MetricSpec("fcf_margin", 0.05, _higher_better(0.0, 0.15), "Free-cash-flow margin"),
    MetricSpec("piotroski_f", 0.08, _higher_better(0.0, 9.0), "Piotroski F-Score"),
    MetricSpec("altman_z", 0.07, _higher_better(1.8, 3.0), "Altman Z-Score"),
]

TOTAL_WEIGHT = sum(s.weight for s in METRIC_SPECS)
MIN_COVERAGE = 0.20  # below this, there is too little data to score honestly


@dataclass(slots=True)
class FundamentalScore:
    score: float | None
    coverage: float
    breakdown: dict[str, Any]


def score_fundamentals(metrics: dict[str, float | None]) -> FundamentalScore:
    """Combine metric values into a 0–100 score with a full breakdown."""
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
        return FundamentalScore(
            score=None,
            coverage=round(coverage, 4),
            breakdown={
                "reason": "insufficient_fundamental_data",
                "coverage": round(coverage, 4),
                "metrics": present,
                "missing": missing,
            },
        )

    score = round(weighted_sum / weight_present, 2)
    return FundamentalScore(
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
