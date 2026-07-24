from __future__ import annotations

from app.engines.composite.dimensions import momentum_score, quality_score, risk_score
from app.models.fundamentals import FinancialRatios
from app.models.technical import TechnicalIndicator


def test_momentum_max() -> None:
    ind = TechnicalIndicator(momentum=0.15, pct_from_52w_high=0.0, rsi_14=60)
    score, bd = momentum_score(ind)
    assert score == 100.0
    assert "metrics" in bd


def test_momentum_none_without_indicator() -> None:
    score, bd = momentum_score(None)
    assert score is None
    assert bd["reason"] == "no_technical_indicators"


def test_quality_max() -> None:
    ratios = FinancialRatios(roe=0.25, net_margin=0.20, gross_margin=0.60,
                             piotroski_f=9, interest_coverage=10)
    score, _ = quality_score(ratios)
    assert score == 100.0


def test_quality_weak() -> None:
    ratios = FinancialRatios(roe=0.0, net_margin=0.0, gross_margin=0.0,
                             piotroski_f=0, interest_coverage=1.0)
    score, _ = quality_score(ratios)
    assert score == 0.0


def test_risk_low_risk_scores_high() -> None:
    ind = TechnicalIndicator(volatility=0.15)
    ratios = FinancialRatios(debt_to_equity=0.0, altman_z=3.0)
    score, _ = risk_score(ind, ratios)
    assert score == 100.0


def test_risk_high_risk_scores_low() -> None:
    ind = TechnicalIndicator(volatility=0.80)
    ratios = FinancialRatios(debt_to_equity=2.5, altman_z=1.8)
    score, _ = risk_score(ind, ratios)
    assert score == 0.0
