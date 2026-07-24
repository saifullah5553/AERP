"""Reusable weighted-scoring primitive shared by the composite dimensions.

Maps metric values to 0–100 sub-scores via per-metric scorers, drops missing
metrics and renormalises the remaining weights, and returns a coverage figure plus
a per-metric breakdown — the same explainability contract used across the engines.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.engines.common import clamp


def higher_better(low: float, high: float) -> Callable[[float], float]:
    return lambda v: clamp((v - low) / (high - low) * 100.0)


def lower_better(low: float, high: float) -> Callable[[float], float]:
    return lambda v: clamp((high - v) / (high - low) * 100.0)


def band(
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
class Spec:
    key: str
    weight: float
    scorer: Callable[[float], float]
    label: str


@dataclass(slots=True)
class WeightedResult:
    score: float | None
    coverage: float
    breakdown: dict[str, Any]


def weighted_score(
    specs: list[Spec], metrics: dict[str, float | None], min_coverage: float = 0.20
) -> WeightedResult:
    total_weight = sum(s.weight for s in specs)
    present: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    weighted_sum = 0.0
    weight_present = 0.0

    for spec in specs:
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

    coverage = weight_present / total_weight if total_weight else 0.0
    if weight_present == 0.0 or coverage < min_coverage:
        return WeightedResult(None, round(coverage, 4), {"metrics": present, "missing": missing})

    return WeightedResult(
        score=round(weighted_sum / weight_present, 2),
        coverage=round(coverage, 4),
        breakdown={"metrics": present, "missing": missing, "coverage": round(coverage, 4)},
    )
