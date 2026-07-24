from __future__ import annotations

import pytest
from app.engines.fundamental.ratios import compute_ratios

from tests import fundamentals_data as fd


@pytest.fixture()
def ratios():
    return compute_ratios(fd.incomes(), fd.balances(), fd.cashflows(), fd.market())


def test_margins(ratios) -> None:
    assert ratios.gross_margin == pytest.approx(500 / 1200, rel=1e-4)
    assert ratios.operating_margin == pytest.approx(320 / 1200, rel=1e-4)
    assert ratios.net_margin == pytest.approx(236 / 1200, rel=1e-4)


def test_returns_use_average_base(ratios) -> None:
    assert ratios.roe == pytest.approx(236 / 1075, rel=1e-4)  # avg equity (1150+1000)/2
    assert ratios.roa == pytest.approx(236 / 2100, rel=1e-4)  # avg assets (2200+2000)/2
    assert ratios.roic == pytest.approx(256 / 1430, rel=1e-3)  # NOPAT 320*0.8 / invested


def test_growth(ratios) -> None:
    assert ratios.revenue_growth == pytest.approx(0.20, rel=1e-4)
    assert ratios.eps_growth == pytest.approx((2.36 - 1.84) / 1.84, rel=1e-4)
    assert ratios.revenue_cagr_3y == pytest.approx(0.20, rel=1e-4)


def test_leverage_and_liquidity(ratios) -> None:
    assert ratios.debt_to_equity == pytest.approx(480 / 1150, rel=1e-4)
    assert ratios.current_ratio == pytest.approx(900 / 420, rel=1e-4)
    assert ratios.quick_ratio == pytest.approx((900 - 210) / 420, rel=1e-4)
    assert ratios.interest_coverage == pytest.approx(320 / 25, rel=1e-4)


def test_cash_flow_and_dividends(ratios) -> None:
    assert ratios.free_cash_flow == pytest.approx(210)
    assert ratios.fcf_margin == pytest.approx(210 / 1200, rel=1e-4)
    assert ratios.payout_ratio == pytest.approx(60 / 236, rel=1e-4)
    assert ratios.dividend_yield == pytest.approx(0.6 / 50, rel=1e-4)
    assert ratios.dividend_growth == pytest.approx(0.20, rel=1e-4)


def test_valuation(ratios) -> None:
    assert ratios.pe_ratio == pytest.approx(5000 / 236, rel=1e-4)
    assert ratios.price_to_sales == pytest.approx(5000 / 1200, rel=1e-4)
    assert ratios.price_to_book == pytest.approx(5000 / 1150, rel=1e-4)
    assert ratios.book_value_per_share == pytest.approx(11.5, rel=1e-4)
    assert ratios.enterprise_value == pytest.approx(5000 + 480 - 200)
    assert ratios.ev_to_ebitda == pytest.approx(5280 / 380, rel=1e-4)


def test_missing_market_yields_null_valuation() -> None:
    r = compute_ratios(fd.incomes(), fd.balances(), fd.cashflows(), None)
    assert r.pe_ratio is None
    assert r.enterprise_value is None
    # ...but profitability from statements alone still computes.
    assert r.net_margin is not None


def test_no_statements_is_all_none() -> None:
    r = compute_ratios([], [], [], fd.market())
    assert r.net_margin is None
    assert r.roe is None
