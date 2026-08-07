"""The scoring rules the framework insists on, asserted rather than assumed.

Every test here encodes a way the previous binary engine got things wrong.
"""

from __future__ import annotations

from app.engines.strategy.fundamental_quality import (
    CATEGORY_POINTS,
    curve,
    score_fundamentals,
    trend,
)


def _company(periods: int = 20, growth: float = 0.10, margin: float = 0.12,
             leverage: float = 0.5, cfo_ratio: float = 1.1,
             roic_drift: float = 0.0) -> dict:
    """A synthetic company with 20 TTM periods, newest first (the stored order)."""
    income, balance, cashflow = [], [], []
    step = (1 + growth) ** 0.25 - 1        # per TTM period, so YoY over four periods == growth
    for i in range(periods):
        # i=0 is the newest, so step BACKWARDS through the growth path.
        rev = 1000.0 * ((1 + step) ** (periods - 1 - i))
        drift = 1 + roic_drift * (periods - 1 - i) / max(1, periods - 1)
        ebit = rev * margin * drift
        ni = ebit * 0.7
        equity = rev * 0.8
        income.append({
            "revenue": rev, "cost_of_revenue": rev * 0.6, "gross_profit": rev * 0.4,
            "operating_income": ebit, "ebitda": ebit * 1.2, "net_income": ni,
            "eps": ni / 100.0, "weighted_shares": 100.0, "interest_expense": rev * 0.01,
            "income_before_tax": ebit, "income_tax_expense": ebit * 0.3,
        })
        balance.append({
            "total_assets": rev * 1.5, "total_equity": equity,
            "total_debt": equity * leverage, "current_assets": rev * 0.5,
            "current_liabilities": rev * 0.25, "inventory": rev * 0.1,
            "receivables": rev * 0.12, "accounts_payable": rev * 0.08,
            "cash_and_equivalents": rev * 0.1, "short_term_investments": 0.0,
        })
        cashflow.append({
            "operating_cash_flow": ni * cfo_ratio, "capital_expenditure": rev * 0.04,
            "free_cash_flow": ni * cfo_ratio - rev * 0.04,
        })
    return {"income": income, "balance": balance, "cashflow": cashflow}


def test_categories_sum_to_100() -> None:
    assert sum(CATEGORY_POINTS.values()) == 100.0


def test_magnitude_beats_pass_fail() -> None:
    """25% growth must score materially above 10%, not merely 'also a pass'."""
    slow = score_fundamentals(_company(growth=0.10)).score
    fast = score_fundamentals(_company(growth=0.25)).score
    assert slow is not None and fast is not None
    assert fast > slow + 2, f"25% growth ({fast}) barely beat 10% ({slow})"


def test_no_band_is_flat_inside_itself() -> None:
    """10.1% must outscore 10.0%. A band that pays the same everywhere is a threshold."""
    knots = [(0.05, 0.35), (0.10, 0.55), (0.15, 0.70)]
    assert curve(0.101, knots) > curve(0.100, knots)
    assert curve(0.149, knots) > curve(0.101, knots)


def test_outliers_are_capped_not_extrapolated() -> None:
    """100x interest cover is excellent, not twenty times as excellent as 5x."""
    knots = [(0.0, 0.0), (3.0, 0.40), (12.0, 0.85), (30.0, 1.0)]
    good, absurd = curve(5.0, knots), curve(100.0, knots)
    assert absurd <= 1.0
    assert absurd < good * 3, "an extreme ratio ran away with the score"


def test_trend_separates_two_identical_levels() -> None:
    """Same margin today: the one that climbed there should outscore the one that fell."""
    improving = score_fundamentals(_company(roic_drift=0.5)).score
    deteriorating = score_fundamentals(_company(roic_drift=-0.5)).score
    assert improving is not None and deteriorating is not None
    assert improving > deteriorating


def test_trend_direction_is_read_oldest_to_newest() -> None:
    """Guards the orientation bug: stored rows are newest-first."""
    assert trend([1.0, 2.0, 3.0, 4.0, 5.0, 6.0]) > 0
    assert trend([6.0, 5.0, 4.0, 3.0, 2.0, 1.0]) < 0


def test_leverage_lowers_the_balance_sheet_score() -> None:
    light = score_fundamentals(_company(leverage=0.3))
    heavy = score_fundamentals(_company(leverage=3.0))
    assert (light.categories["balance_sheet"]["earned"]
            > heavy.categories["balance_sheet"]["earned"])


def test_weak_cash_conversion_is_penalised() -> None:
    """Profit that never becomes cash must cost the company points."""
    cashy = score_fundamentals(_company(cfo_ratio=1.2))
    paper = score_fundamentals(_company(cfo_ratio=0.4))
    assert cashy.score > paper.score
    assert any("not backed by operating cash" in f for f in paper.flags)


def test_the_score_carries_no_country_assumption() -> None:
    """Identical statements score identically, whatever market they came from.

    The engine used to deflate growth by a per-market inflation figure and score interest cover
    against a per-market floor. Both are gone: one assumed constant moved every score in a
    market, which made the number a view on the economy rather than a reading of the accounts.
    """
    import app.engines.strategy.fundamental_quality as fq
    assert not hasattr(fq, "COUNTRY_INFLATION")
    assert not hasattr(fq, "COUNTRY_COVERAGE_FLOOR")
    a = score_fundamentals(_company(growth=0.12), sector="Cement").score
    b = score_fundamentals(_company(growth=0.12), sector="Cement").score
    assert a == b


def test_a_bank_skips_metrics_that_do_not_apply() -> None:
    """No inventory, no cash-conversion cycle, no ROIC - and still scored out of 100.

    ROIC now lives in working capital, which a bank skips entirely, so it drops out with the
    category rather than needing its own exemption. A bank's debt is its funding, not its
    leverage, and dividing by it produces a number that means nothing.
    """
    bank = score_fundamentals(_company(), sector="Commercial Banks")
    assert bank.categories["working_capital"]["points"] == 0.0
    assert "roic" not in bank.categories["working_capital"].get("parts", {})
    # Liquidity still applies - cash cover is meaningful for a bank - but the industrial
    # current/quick ratios inside it do not.
    liq = bank.categories["liquidity"]["parts"]
    assert liq["current_ratio"] is None and liq["quick_ratio"] is None
    assert liq["cash_to_debt"] is not None
    assert bank.score is not None and 0 <= bank.score <= 100


def test_confidence_falls_with_shorter_history() -> None:
    deep = score_fundamentals(_company(periods=20))
    thin = score_fundamentals(_company(periods=5))
    assert deep.confidence > thin.confidence
    assert deep.periods == 20


def test_nothing_is_invented_when_there_is_no_data() -> None:
    empty = score_fundamentals({"income": [], "balance": [], "cashflow": []})
    assert empty.score is None
    assert empty.grade == "Unrated"


def test_margins_are_judged_against_the_industry() -> None:
    """A 12% margin is strong in groceries and thin in software.

    Absolute level still leads - a company is not high quality merely for being the best of a
    poor sector - but the peer median has to move the number, or sector normalisation is a
    comment rather than a mechanism.
    """
    st = _company(margin=0.12)
    grocery = score_fundamentals(st, peers={"operating_margin": 0.04})
    software = score_fundamentals(st, peers={"operating_margin": 0.30})
    assert (grocery.categories["profitability"]["earned"]
            > software.categories["profitability"]["earned"])


def test_growth_curve_matches_the_specified_table() -> None:
    """5% -> 2.1/5, 10% -> 3.0, 15% -> 3.7, 20% -> 4.4, 25% -> 5.0."""
    from app.engines.strategy.fundamental_quality import _GROWTH_KNOTS
    expected = {0.05: 2.1, 0.10: 3.0, 0.15: 3.7, 0.20: 4.4, 0.25: 5.0}
    for growth, points in expected.items():
        assert abs(curve(growth, _GROWTH_KNOTS) * 5 - points) < 0.05, growth
    # Full marks at 25% and flat above: a freak year cannot buy more than compounding does.
    assert curve(2.0, _GROWTH_KNOTS) == curve(0.25, _GROWTH_KNOTS)


def test_roic_curve_matches_the_specified_table() -> None:
    """6% -> 2.0/8, 10% -> 3.2, 15% -> 4.8, 20% -> 6.5, 25% -> 7.5, 30% -> 8.0."""
    from app.engines.strategy.fundamental_quality import _RETURN_KNOTS
    expected = {0.06: 2.0, 0.10: 3.2, 0.15: 4.8, 0.20: 6.5, 0.25: 7.5, 0.30: 8.0}
    for roic, points in expected.items():
        assert abs(curve(roic, _RETURN_KNOTS) * 8 - points) < 0.05, roic


def test_the_curves_interpolate_between_the_table_rows() -> None:
    """The table gives anchors, not buckets: 12% must land between the 10% and 15% rows."""
    from app.engines.strategy.fundamental_quality import _RETURN_KNOTS
    at_12 = curve(0.12, _RETURN_KNOTS) * 8
    assert 3.2 < at_12 < 4.8
    assert curve(0.121, _RETURN_KNOTS) > curve(0.120, _RETURN_KNOTS)
