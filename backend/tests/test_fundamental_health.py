from __future__ import annotations

import pytest
from app.engines.fundamental.health import altman_z_score, piotroski_f_score

from tests import fundamentals_data as fd


def test_piotroski_perfect_nine() -> None:
    result = piotroski_f_score(fd.incomes(), fd.balances(), fd.cashflows())
    assert result.score == 9
    assert all(result.criteria.values())


def test_piotroski_needs_two_periods() -> None:
    result = piotroski_f_score(fd.incomes()[:1], fd.balances()[:1], fd.cashflows()[:1])
    assert result.score is None


def test_piotroski_detects_dilution() -> None:
    incomes = fd.incomes()
    incomes[-1].weighted_shares = 120  # shares increased vs prior 100
    result = piotroski_f_score(incomes, fd.balances(), fd.cashflows())
    assert result.criteria["no_dilution"] is False
    assert result.score == 8


def test_altman_z_safe_zone() -> None:
    z = altman_z_score(fd.incomes()[-1], fd.balances()[-1], market_cap=5000.0)
    assert z == pytest.approx(4.62, abs=0.05)
    assert z > 2.99  # safe zone


def test_altman_z_none_without_balance() -> None:
    assert altman_z_score(fd.incomes()[-1], None, market_cap=5000.0) is None
