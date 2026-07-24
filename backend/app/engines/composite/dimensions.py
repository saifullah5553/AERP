"""Momentum, quality, and risk dimensions for the composite score.

These are computed from data the earlier engines already stored — the latest
``TechnicalIndicator`` and ``FinancialRatios`` rows — so the composite never
recomputes indicators or ratios, only re-weights them into focused sub-scores.
Each returns a 0–100 score (or ``None``) with an explainable breakdown.
"""

from __future__ import annotations

from typing import Any

from app.engines.common import f
from app.engines.scoring_util import Spec, band, higher_better, lower_better, weighted_score

# ── Momentum: recent price behaviour ──────────────────────────
_MOMENTUM = [
    Spec("momentum", 0.45, higher_better(-0.15, 0.15), "3-month price momentum"),
    Spec("pct_from_52w_high", 0.30, higher_better(-0.5, 0.0), "Proximity to 52w high"),
    Spec("rsi", 0.25, band(50, 70, 30, 90), "RSI(14) zone"),
]

# ── Quality: durability of the business ───────────────────────
_QUALITY = [
    Spec("roe", 0.25, higher_better(0.0, 0.25), "Return on equity"),
    Spec("net_margin", 0.20, higher_better(0.0, 0.20), "Net margin"),
    Spec("gross_margin", 0.15, higher_better(0.0, 0.60), "Gross margin"),
    Spec("piotroski_f", 0.25, higher_better(0.0, 9.0), "Piotroski F-Score"),
    Spec("interest_coverage", 0.15, higher_better(1.0, 10.0), "Interest coverage"),
]

# ── Risk: higher score == lower risk ──────────────────────────
_RISK = [
    Spec("volatility", 0.40, lower_better(0.15, 0.80), "Annualised volatility"),
    Spec("debt_to_equity", 0.35, lower_better(0.0, 2.5), "Debt / equity"),
    Spec("altman_z", 0.25, higher_better(1.8, 3.0), "Altman Z-Score"),
]


def momentum_score(indicator: Any | None) -> tuple[float | None, dict[str, Any]]:
    if indicator is None:
        return None, {"reason": "no_technical_indicators"}
    metrics = {
        "momentum": f(indicator.momentum),
        "pct_from_52w_high": f(indicator.pct_from_52w_high),
        "rsi": f(indicator.rsi_14),
    }
    r = weighted_score(_MOMENTUM, metrics)
    return r.score, r.breakdown


def quality_score(ratios: Any | None) -> tuple[float | None, dict[str, Any]]:
    if ratios is None:
        return None, {"reason": "no_financial_ratios"}
    metrics = {
        "roe": f(ratios.roe),
        "net_margin": f(ratios.net_margin),
        "gross_margin": f(ratios.gross_margin),
        "piotroski_f": f(ratios.piotroski_f),
        "interest_coverage": f(ratios.interest_coverage),
    }
    r = weighted_score(_QUALITY, metrics)
    return r.score, r.breakdown


def risk_score(
    indicator: Any | None, ratios: Any | None
) -> tuple[float | None, dict[str, Any]]:
    if indicator is None and ratios is None:
        return None, {"reason": "no_risk_inputs"}
    metrics = {
        "volatility": f(getattr(indicator, "volatility", None)),
        "debt_to_equity": f(getattr(ratios, "debt_to_equity", None)),
        "altman_z": f(getattr(ratios, "altman_z", None)),
    }
    r = weighted_score(_RISK, metrics)
    return r.score, r.breakdown
