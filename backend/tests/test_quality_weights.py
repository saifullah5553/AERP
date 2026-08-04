from __future__ import annotations

from app.engines.strategy.quality import CHECK_WEIGHTS, assess_quality


def _company(debt=400.0, ebitda=250.0, interest=-20.0, cur_assets=600.0, cur_liab=300.0,
             cash=100.0, receivables=200.0, inventory=None, revenue=1000.0,
             gross_profit=400.0, op_income=200.0, net_income=150.0, ocf=180.0, fcf=120.0):
    """One reported period. Defaults describe a sound, profitable, unlevered business."""
    bal = {"fiscal_date": "2025-12-31", "total_equity": 500.0, "total_assets": 1200.0,
           "total_debt": debt, "cash_and_equivalents": cash, "receivables": receivables,
           "current_assets": cur_assets, "current_liabilities": cur_liab}
    if inventory is not None:
        bal["inventory"] = inventory
    return {
        "income": [{"fiscal_date": "2025-12-31", "revenue": revenue,
                    "gross_profit": gross_profit, "operating_income": op_income,
                    "net_income": net_income, "eps": 1.5, "ebitda": ebitda,
                    "interest_expense": interest}],
        "balance": [bal],
        "cashflow": [{"fiscal_date": "2025-12-31", "operating_cash_flow": ocf,
                      "free_cash_flow": fcf}],
    }


def test_the_pillars_carry_their_stated_weights() -> None:
    """Growth 35 / margins 15 / cash 25 / solvency and liquidity 25.

    Pinned because this is the stated investment thesis, not an implementation detail: if these
    drift, the score quietly stops measuring what it claims to.
    """
    growth = sum(CHECK_WEIGHTS[k] for k in
                 ("revenue_rising", "operating_profit_rising", "eps_rising"))
    margins = sum(CHECK_WEIGHTS[k] for k in
                  ("gross_margin_healthy", "operating_margin_healthy", "net_margin_healthy"))
    cash = sum(CHECK_WEIGHTS[k] for k in
               ("cash_flow_positive", "free_cash_flow_positive",
                "earnings_backed_by_cash", "cash_building"))
    solvency = sum(CHECK_WEIGHTS[k] for k in
                   ("net_debt_to_ebitda_safe", "interest_coverage_safe",
                    "debt_to_equity_reasonable", "current_ratio_healthy",
                    "quick_ratio_healthy"))

    assert round(growth, 2) == 0.35
    assert round(margins, 2) == 0.15
    assert round(cash, 2) == 0.25
    assert round(solvency, 2) == 0.25
    assert round(sum(CHECK_WEIGHTS.values()), 4) == 1.0

    # OCF vs net income is the closest thing to a lie detector on reported profit. At the 2.5%
    # it previously carried, it was decorative.
    assert CHECK_WEIGHTS["earnings_backed_by_cash"] >= 0.05

    # This is a business-quality score. Price is a separate question, so nothing price-based
    # contributes to it - a great company is not made worse by being expensive.
    for priced in ("earnings_yield_attractive", "fcf_yield_attractive",
                   "price_to_book_reasonable", "margin_of_safety"):
        assert priced not in CHECK_WEIGHTS


def test_leverage_can_no_longer_be_waved_through() -> None:
    """The old pillar was one test - "debt is low OR fell" - so a company at 2.8x debt-to-equity
    passed the whole 20% by repaying a token amount. Now five ratios have to agree."""
    sound = assess_quality(_company())
    levered = assess_quality(_company(debt=1400.0, interest=-180.0, cur_assets=300.0,
                                      cur_liab=400.0, cash=20.0, receivables=60.0))

    assert levered.checks["net_debt_to_ebitda_safe"] is False     # 5.5x
    assert levered.checks["interest_coverage_safe"] is False      # 1.1x
    assert levered.checks["quick_ratio_healthy"] is False
    assert sound.score - levered.score >= 25


def test_quick_ratio_excludes_inventory() -> None:
    """Inventory is the slowest current asset to turn into cash, and the first to stop selling
    when a business gets into trouble - so it cannot count toward immediate survival."""
    q = assess_quality(_company(cur_assets=900.0, cur_liab=400.0, cash=50.0,
                                receivables=100.0, inventory=750.0))
    assert q.checks["current_ratio_healthy"] is True    # 2.25x, flattered by inventory
    assert q.checks["quick_ratio_healthy"] is False     # 0.38x once inventory is excluded


def test_interest_coverage_survives_the_sign_convention() -> None:
    """Interest expense is reported as a negative (an outflow) by some exchanges and a positive
    by others. A sign convention must not decide whether a company looks solvent."""
    assert assess_quality(_company(interest=-20.0)).checks["interest_coverage_safe"] is True
    assert assess_quality(_company(interest=20.0)).checks["interest_coverage_safe"] is True
    # No debt to service is not a failure to cover it.
    assert assess_quality(
        _company(interest=None, debt=0.0)).checks["interest_coverage_safe"] is True


def test_net_debt_nets_off_cash() -> None:
    """A company holding its debt in cash is not levered in any way that matters."""
    gross_only = assess_quality(_company(debt=800.0, cash=20.0, ebitda=250.0))
    net_cash = assess_quality(_company(debt=800.0, cash=750.0, ebitda=250.0))
    assert gross_only.checks["net_debt_to_ebitda_safe"] is False   # 3.1x
    assert net_cash.checks["net_debt_to_ebitda_safe"] is True      # 0.2x


def test_cash_generation_outweighs_a_tidy_balance_sheet() -> None:
    """Same company twice, differing only in whether it generates cash."""
    generating = assess_quality(_company(ocf=180.0, fcf=120.0))
    burning = assess_quality(_company(ocf=-180.0, fcf=-220.0))
    assert generating.score is not None and burning.score is not None
    assert generating.score > burning.score


def test_returns_are_computed_even_though_they_are_not_scored() -> None:
    """ROE and ROA are no longer weighted, but the company page still shows them - dropping the
    calculation would quietly empty those fields."""
    q = assess_quality(_company())
    assert q.metrics["roe"] == 150.0 / 500.0
    assert q.metrics["roa"] == 150.0 / 1200.0
    assert q.metrics["gross_margin"] == 400.0 / 1000.0


def test_growth_is_banded_with_over_20_percent_at_the_top() -> None:
    """Growth is not experienced linearly - the gap between 2% and 7% is a different kind of
    difference from 22% to 27% - so it is banded, and the bands are legible."""
    from app.engines.strategy.quality import _band

    assert _band(-0.05) == 0      # shrinking
    assert _band(0.03) == 20      # under 5%
    assert _band(0.07) == 40      # under 10%
    assert _band(0.12) == 60      # under 15%
    assert _band(0.18) == 80      # under 20%
    assert _band(0.25) == 100     # over 20%
    assert _band(0.60) == 100     # and no more credit beyond that
    assert _band(None) is None


def test_higher_growth_scores_higher() -> None:
    """The whole point of grading: a binary check made 2% and 35% growth identical."""
    def grower(rate):
        older = 1000.0 / (1 + rate)
        return {
            "income": [
                {"fiscal_date": "2025-12-31", "revenue": 1000.0, "gross_profit": 400.0,
                 "operating_income": 200.0, "net_income": 150.0, "eps": 1.5, "ebitda": 250.0,
                 "interest_expense": -20.0},
                {"fiscal_date": "2024-12-31", "revenue": older, "gross_profit": 380.0,
                 "operating_income": 180.0, "net_income": 130.0, "eps": 1.3},
            ],
            "balance": [{"fiscal_date": "2025-12-31", "total_equity": 500.0,
                         "total_assets": 1200.0, "total_debt": 400.0,
                         "cash_and_equivalents": 100.0, "receivables": 200.0,
                         "current_assets": 600.0, "current_liabilities": 300.0}],
            "cashflow": [{"fiscal_date": "2025-12-31", "operating_cash_flow": 180.0,
                          "free_cash_flow": 120.0}],
        }

    slow = assess_quality(grower(0.02))
    fast = assess_quality(grower(0.35))
    assert fast.score > slow.score
    assert fast.grades["revenue_rising"] > slow.grades["revenue_rising"]


def test_margins_are_graded_against_peers_not_a_fixed_line() -> None:
    """25% gross margin is poor for software and excellent for a grocer. A fixed threshold does
    not rank companies, it ranks industries."""
    st = _company(gross_profit=300.0, revenue=1000.0)     # 30% gross margin

    software = assess_quality(st, peers={"gross_margin": 0.70})
    grocery = assess_quality(st, peers={"gross_margin": 0.15})

    assert software.grades["gross_margin_healthy"] == 0.0
    assert grocery.grades["gross_margin_healthy"] == 100.0
    assert grocery.score > software.score


def test_a_loss_making_peer_group_falls_back_to_absolute_anchors() -> None:
    """A negative median cannot anchor a relative score, and pretending otherwise would rank
    companies against nonsense."""
    st = _company(gross_profit=300.0, revenue=1000.0)
    q = assess_quality(st, peers={"gross_margin": -0.10})
    # Absolute anchors put 30% gross margin at 60.
    assert q.grades["gross_margin_healthy"] == 60.0
