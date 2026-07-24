from __future__ import annotations

from app.engines.fundamental.scoring import score_fundamentals

STRONG = {
    "roe": 0.25, "net_margin": 0.20, "roa": 0.12, "gross_margin": 0.60,
    "revenue_growth": 0.25, "eps_growth": 0.30, "debt_to_equity": 0.0,
    "current_ratio": 2.0, "interest_coverage": 10.0, "fcf_margin": 0.15,
    "piotroski_f": 9.0, "altman_z": 3.0,
}


def test_all_max_scores_100_full_coverage() -> None:
    result = score_fundamentals(STRONG)
    assert result.score == 100.0
    assert result.coverage == 1.0
    assert result.breakdown["metrics"]["roe"]["sub_score"] == 100.0


def test_weak_company_scores_low() -> None:
    weak = {
        "roe": -0.10, "net_margin": -0.05, "roa": -0.02, "gross_margin": 0.05,
        "revenue_growth": -0.20, "eps_growth": -0.30, "debt_to_equity": 3.0,
        "current_ratio": 0.5, "interest_coverage": 1.0, "fcf_margin": -0.05,
        "piotroski_f": 1.0, "altman_z": 1.5,
    }
    result = score_fundamentals(weak)
    assert result.score is not None
    assert result.score < 20.0


def test_lower_better_and_missing_renormalises() -> None:
    # Only two metrics present; both perfect → score 100 but coverage < 1.
    result = score_fundamentals({"debt_to_equity": 0.0, "roe": 0.25})
    assert result.score == 100.0
    assert 0 < result.coverage < 1.0
    assert set(result.breakdown["metrics"]) == {"debt_to_equity", "roe"}


def test_insufficient_data_returns_none() -> None:
    result = score_fundamentals({"gross_margin": 0.40})  # weight 0.06 < 0.20 coverage
    assert result.score is None
    assert result.breakdown["reason"] == "insufficient_fundamental_data"


def test_empty_metrics_returns_none() -> None:
    assert score_fundamentals({}).score is None
