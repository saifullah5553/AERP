from __future__ import annotations

from app.engines.technical.scoring import score_technical

STRONG = {
    "above_sma50": 1.0, "above_sma200": 1.0, "golden_cross": 1.0, "supertrend": 1.0,
    "macd_hist_norm": 0.02, "rsi": 60.0, "momentum": 0.15, "adx": 40.0,
    "pct_from_52w_high": 0.0, "above_vwap": 1.0, "obv_trend": 1.0, "mfi": 65.0,
}

WEAK = {
    "above_sma50": 0.0, "above_sma200": 0.0, "golden_cross": 0.0, "supertrend": 0.0,
    "macd_hist_norm": -0.02, "rsi": 25.0, "momentum": -0.15, "adx": 15.0,
    "pct_from_52w_high": -0.5, "above_vwap": 0.0, "obv_trend": 0.0, "mfi": 15.0,
}


def test_strong_trend_scores_high() -> None:
    result = score_technical(STRONG)
    assert result.score == 100.0
    assert result.coverage == 1.0


def test_weak_trend_scores_low() -> None:
    result = score_technical(WEAK)
    assert result.score is not None
    assert result.score < 10.0


def test_partial_coverage_renormalises() -> None:
    result = score_technical({"above_sma50": 1.0, "rsi": 60.0, "momentum": 0.15})
    assert result.score == 100.0
    assert 0 < result.coverage < 1.0


def test_insufficient_returns_none() -> None:
    result = score_technical({"above_vwap": 1.0})  # weight 0.06 < 0.20 coverage
    assert result.score is None
    assert result.breakdown["reason"] == "insufficient_price_history"
