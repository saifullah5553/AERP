from __future__ import annotations

from app.engines.strategy.quality import CHECK_WEIGHTS, assess_quality


def test_the_pillars_carry_their_stated_weights() -> None:
    """Growth 40 / cash 20 / debt 20 / valuation 20.

    Pinned because this is the stated investment thesis, not an implementation detail: if these
    drift, the score quietly stops measuring what it claims to.
    """
    growth = sum(CHECK_WEIGHTS[k] for k in
                 ("revenue_rising", "operating_profit_rising", "eps_rising"))
    cash = sum(CHECK_WEIGHTS[k] for k in
               ("cash_flow_positive", "free_cash_flow_positive", "earnings_backed_by_cash",
                "cash_reserves_healthy", "cash_building"))
    debt = CHECK_WEIGHTS["debt_low_or_falling"]
    valuation = sum(CHECK_WEIGHTS[k] for k in
                    ("earnings_yield_attractive", "fcf_yield_attractive",
                     "price_to_book_reasonable", "margin_of_safety"))
    returns = sum(CHECK_WEIGHTS[k] for k in
                  ("roe_strong", "roa_strong",
                   "operating_margin_healthy", "net_margin_healthy"))

    assert round(growth, 2) == 0.40
    assert round(cash, 2) == 0.20
    assert round(debt, 2) == 0.20
    assert round(valuation + returns, 2) == 0.20
    assert round(sum(CHECK_WEIGHTS.values()), 4) == 1.0

    # Within the cash pillar, actually generating cash outweighs the corroborating tests.
    assert CHECK_WEIGHTS["cash_flow_positive"] > CHECK_WEIGHTS["cash_reserves_healthy"]
    assert CHECK_WEIGHTS["free_cash_flow_positive"] > CHECK_WEIGHTS["cash_building"]


def _statements(revenue, op, eps, ocf, fcf, cash, debt, equity):
    """Newest-first statements across four periods from oldest->newest inputs."""
    def rows(vals, key, extra=None):
        out = []
        for i, v in enumerate(reversed(vals)):
            row = {"fiscal_date": f"202{5 - i}-12-31", key: v}
            if extra:
                row.update({k: seq[len(vals) - 1 - i] for k, seq in extra.items()})
            out.append(row)
        return out

    return {
        "income": [{"fiscal_date": f"202{5 - i}-12-31",
                    "revenue": list(reversed(revenue))[i],
                    "operating_income": list(reversed(op))[i],
                    "eps": list(reversed(eps))[i]} for i in range(len(revenue))],
        "cashflow": [{"fiscal_date": f"202{5 - i}-12-31",
                      "operating_cash_flow": list(reversed(ocf))[i],
                      "free_cash_flow": list(reversed(fcf))[i]} for i in range(len(ocf))],
        "balance": [{"fiscal_date": f"202{5 - i}-12-31",
                     "cash_and_equivalents": list(reversed(cash))[i],
                     "total_debt": list(reversed(debt))[i],
                     "total_equity": list(reversed(equity))[i]} for i in range(len(cash))],
    }


def test_cash_generation_outweighs_a_tidy_balance_sheet() -> None:
    # Same company twice, differing only in whether it generates cash. Under the old pillar
    # average, five cash checks shared one pillar and "reserves look healthy" could mask a
    # business that produces no operating cash. It cannot now.
    generating = assess_quality(_statements(
        revenue=[100, 110, 120, 130], op=[10, 12, 14, 16], eps=[1.0, 1.2, 1.4, 1.6],
        ocf=[20, 22, 24, 26], fcf=[10, 12, 14, 16],
        cash=[50, 55, 60, 65], debt=[40, 38, 36, 34], equity=[200, 210, 220, 230]))
    burning = assess_quality(_statements(
        revenue=[100, 110, 120, 130], op=[10, 12, 14, 16], eps=[1.0, 1.2, 1.4, 1.6],
        ocf=[-20, -22, -24, -26], fcf=[-30, -32, -34, -36],
        cash=[50, 55, 60, 65], debt=[40, 38, 36, 34], equity=[200, 210, 220, 230]))

    assert generating.score is not None and burning.score is not None
    assert generating.score > burning.score


def test_valuation_is_scored_only_when_we_have_a_price() -> None:
    """A company we cannot price must not be scored as though it were expensive.

    That would quietly punish illiquid names - exactly where a quote is hardest to get - so the
    valuation checks stay unknown and the remaining weights renormalise.
    """
    st = _statements(
        revenue=[100, 110, 120, 130], op=[10, 12, 14, 16], eps=[1.0, 1.2, 1.4, 1.6],
        ocf=[20, 22, 24, 26], fcf=[10, 12, 14, 16],
        cash=[50, 55, 60, 65], debt=[40, 38, 36, 34], equity=[200, 210, 220, 230])

    unpriced = assess_quality(st)
    cheap = assess_quality(st, market={"price": 5.0, "market_cap": 100.0})
    dear = assess_quality(st, market={"price": 200.0, "market_cap": 8000.0})

    assert all(unpriced.checks[k] is None for k in
               ("earnings_yield_attractive", "fcf_yield_attractive",
                "price_to_book_reasonable", "margin_of_safety"))
    assert cheap.score > dear.score
    # Valuation is 10% of the score, so the whole gap lives inside it.
    assert 3 <= (cheap.score - dear.score) <= 15

    # Price changes what a business is WORTH, never whether it is sound. Collapsing the two
    # would hide a good company that is merely expensive.
    assert cheap.passed == dear.passed == unpriced.passed


def test_returns_are_scored_without_a_price() -> None:
    """ROE, ROA and margins come from the accounts alone.

    That is the point of splitting the last pillar: a company with no quote still gets judged
    on how well it turns capital and sales into profit.
    """
    strong = assess_quality({
        "income": [{"fiscal_date": "2025-12-31", "revenue": 1000.0, "operating_income": 200.0,
                    "net_income": 150.0, "eps": 1.5}],
        "balance": [{"fiscal_date": "2025-12-31", "total_equity": 500.0,
                     "total_assets": 1200.0}],
        "cashflow": [{"fiscal_date": "2025-12-31", "operating_cash_flow": 180.0}],
    })
    weak = assess_quality({
        "income": [{"fiscal_date": "2025-12-31", "revenue": 1000.0, "operating_income": 20.0,
                    "net_income": 10.0, "eps": 0.1}],
        "balance": [{"fiscal_date": "2025-12-31", "total_equity": 500.0,
                     "total_assets": 1200.0}],
        "cashflow": [{"fiscal_date": "2025-12-31", "operating_cash_flow": 15.0}],
    })

    assert strong.checks["roe_strong"] is True          # 150/500 = 30%
    assert strong.checks["operating_margin_healthy"] is True
    assert weak.checks["roe_strong"] is False           # 10/500 = 2%
    assert weak.checks["net_margin_healthy"] is False   # 1%
    # No market data was passed, yet these still resolved.
    assert strong.checks["earnings_yield_attractive"] is None
