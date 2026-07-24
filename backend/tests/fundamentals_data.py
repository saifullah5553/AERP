"""Deterministic two-year statement fixtures shared by fundamental-engine tests.

Returns real ORM statement instances (unbound to a session) so tests exercise the
same objects the engine reads in production.
"""

from __future__ import annotations

from datetime import date

from app.engines.fundamental.ratios import MarketInputs
from app.models.enums import StatementPeriod
from app.models.fundamentals import BalanceSheet, CashFlowStatement, IncomeStatement

ANNUAL = StatementPeriod.ANNUAL


def incomes(security_id: int | None = None) -> list[IncomeStatement]:
    return [
        IncomeStatement(
            security_id=security_id, period=ANNUAL, fiscal_date=date(2024, 12, 31),
            revenue=1000, cost_of_revenue=600, gross_profit=400, operating_income=250,
            ebit=250, ebitda=300, interest_expense=20, income_before_tax=230,
            income_tax_expense=46, net_income=184, eps=1.84, weighted_shares=100,
        ),
        IncomeStatement(
            security_id=security_id, period=ANNUAL, fiscal_date=date(2025, 12, 31),
            revenue=1200, cost_of_revenue=700, gross_profit=500, operating_income=320,
            ebit=320, ebitda=380, interest_expense=25, income_before_tax=295,
            income_tax_expense=59, net_income=236, eps=2.36, weighted_shares=100,
        ),
    ]


def balances(security_id: int | None = None) -> list[BalanceSheet]:
    return [
        BalanceSheet(
            security_id=security_id, period=ANNUAL, fiscal_date=date(2024, 12, 31),
            total_assets=2000, total_equity=1000, total_debt=500, current_assets=800,
            current_liabilities=400, inventory=200, cash_and_equivalents=150,
            long_term_debt=400, total_liabilities=1000, retained_earnings=600,
        ),
        BalanceSheet(
            security_id=security_id, period=ANNUAL, fiscal_date=date(2025, 12, 31),
            total_assets=2200, total_equity=1150, total_debt=480, current_assets=900,
            current_liabilities=420, inventory=210, cash_and_equivalents=200,
            long_term_debt=380, total_liabilities=1050, retained_earnings=750,
        ),
    ]


def cashflows(security_id: int | None = None) -> list[CashFlowStatement]:
    return [
        CashFlowStatement(
            security_id=security_id, period=ANNUAL, fiscal_date=date(2024, 12, 31),
            operating_cash_flow=250, capital_expenditure=-80, free_cash_flow=170,
            dividends_paid=-50,
        ),
        CashFlowStatement(
            security_id=security_id, period=ANNUAL, fiscal_date=date(2025, 12, 31),
            operating_cash_flow=300, capital_expenditure=-90, free_cash_flow=210,
            dividends_paid=-60,
        ),
    ]


def market() -> MarketInputs:
    return MarketInputs(price=50.0, shares_outstanding=100.0, market_cap=5000.0)
