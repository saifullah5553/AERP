"""Fundamental data: financial statements, ratios, snapshots, estimates.

Monetary line items use ``Numeric(24, 4)`` (reporting currency, no unit scaling).
Every statement row is keyed by ``(security_id, period, fiscal_date)`` so ingestion
can upsert idempotently.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import (
    Date,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enums import StatementPeriod


class IncomeStatement(Base, TimestampMixin):
    __tablename__ = "income_statements"
    __table_args__ = (
        UniqueConstraint(
            "security_id", "period", "fiscal_date", name="uq_income_sec_period_date"
        ),
        Index("ix_income_security_date", "security_id", "fiscal_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE"), nullable=False
    )
    period: Mapped[StatementPeriod] = mapped_column(Enum(StatementPeriod, native_enum=False))
    fiscal_date: Mapped[date] = mapped_column(Date, nullable=False)
    reported_currency: Mapped[str | None] = mapped_column(String(8))

    revenue: Mapped[float | None] = mapped_column(Numeric(24, 4))
    cost_of_revenue: Mapped[float | None] = mapped_column(Numeric(24, 4))
    gross_profit: Mapped[float | None] = mapped_column(Numeric(24, 4))
    operating_expenses: Mapped[float | None] = mapped_column(Numeric(24, 4))
    operating_income: Mapped[float | None] = mapped_column(Numeric(24, 4))
    ebitda: Mapped[float | None] = mapped_column(Numeric(24, 4))
    ebit: Mapped[float | None] = mapped_column(Numeric(24, 4))
    interest_expense: Mapped[float | None] = mapped_column(Numeric(24, 4))
    income_before_tax: Mapped[float | None] = mapped_column(Numeric(24, 4))
    income_tax_expense: Mapped[float | None] = mapped_column(Numeric(24, 4))
    net_income: Mapped[float | None] = mapped_column(Numeric(24, 4))
    eps: Mapped[float | None] = mapped_column(Numeric(20, 6))
    eps_diluted: Mapped[float | None] = mapped_column(Numeric(20, 6))
    weighted_shares: Mapped[float | None] = mapped_column(Numeric(24, 2))


class BalanceSheet(Base, TimestampMixin):
    __tablename__ = "balance_sheets"
    __table_args__ = (
        UniqueConstraint(
            "security_id", "period", "fiscal_date", name="uq_balance_sec_period_date"
        ),
        Index("ix_balance_security_date", "security_id", "fiscal_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE"), nullable=False
    )
    period: Mapped[StatementPeriod] = mapped_column(Enum(StatementPeriod, native_enum=False))
    fiscal_date: Mapped[date] = mapped_column(Date, nullable=False)
    reported_currency: Mapped[str | None] = mapped_column(String(8))

    cash_and_equivalents: Mapped[float | None] = mapped_column(Numeric(24, 4))
    short_term_investments: Mapped[float | None] = mapped_column(Numeric(24, 4))
    receivables: Mapped[float | None] = mapped_column(Numeric(24, 4))
    inventory: Mapped[float | None] = mapped_column(Numeric(24, 4))
    current_assets: Mapped[float | None] = mapped_column(Numeric(24, 4))
    property_plant_equipment: Mapped[float | None] = mapped_column(Numeric(24, 4))
    goodwill_intangibles: Mapped[float | None] = mapped_column(Numeric(24, 4))
    total_assets: Mapped[float | None] = mapped_column(Numeric(24, 4))

    accounts_payable: Mapped[float | None] = mapped_column(Numeric(24, 4))
    short_term_debt: Mapped[float | None] = mapped_column(Numeric(24, 4))
    current_liabilities: Mapped[float | None] = mapped_column(Numeric(24, 4))
    long_term_debt: Mapped[float | None] = mapped_column(Numeric(24, 4))
    total_debt: Mapped[float | None] = mapped_column(Numeric(24, 4))
    total_liabilities: Mapped[float | None] = mapped_column(Numeric(24, 4))
    retained_earnings: Mapped[float | None] = mapped_column(Numeric(24, 4))
    total_equity: Mapped[float | None] = mapped_column(Numeric(24, 4))


class CashFlowStatement(Base, TimestampMixin):
    __tablename__ = "cash_flow_statements"
    __table_args__ = (
        UniqueConstraint(
            "security_id", "period", "fiscal_date", name="uq_cashflow_sec_period_date"
        ),
        Index("ix_cashflow_security_date", "security_id", "fiscal_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE"), nullable=False
    )
    period: Mapped[StatementPeriod] = mapped_column(Enum(StatementPeriod, native_enum=False))
    fiscal_date: Mapped[date] = mapped_column(Date, nullable=False)
    reported_currency: Mapped[str | None] = mapped_column(String(8))

    operating_cash_flow: Mapped[float | None] = mapped_column(Numeric(24, 4))
    capital_expenditure: Mapped[float | None] = mapped_column(Numeric(24, 4))
    free_cash_flow: Mapped[float | None] = mapped_column(Numeric(24, 4))
    investing_cash_flow: Mapped[float | None] = mapped_column(Numeric(24, 4))
    financing_cash_flow: Mapped[float | None] = mapped_column(Numeric(24, 4))
    dividends_paid: Mapped[float | None] = mapped_column(Numeric(24, 4))
    stock_repurchase: Mapped[float | None] = mapped_column(Numeric(24, 4))
    net_change_in_cash: Mapped[float | None] = mapped_column(Numeric(24, 4))


class FinancialRatios(Base, TimestampMixin):
    """Computed ratios per reporting period (output of the fundamental engine)."""

    __tablename__ = "financial_ratios"
    __table_args__ = (
        UniqueConstraint(
            "security_id", "period", "fiscal_date", name="uq_ratios_sec_period_date"
        ),
        Index("ix_ratios_security_date", "security_id", "fiscal_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE"), nullable=False
    )
    period: Mapped[StatementPeriod] = mapped_column(Enum(StatementPeriod, native_enum=False))
    fiscal_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Profitability
    gross_margin: Mapped[float | None] = mapped_column(Numeric(12, 6))
    operating_margin: Mapped[float | None] = mapped_column(Numeric(12, 6))
    net_margin: Mapped[float | None] = mapped_column(Numeric(12, 6))
    roe: Mapped[float | None] = mapped_column(Numeric(12, 6))
    roa: Mapped[float | None] = mapped_column(Numeric(12, 6))
    roic: Mapped[float | None] = mapped_column(Numeric(12, 6))

    # Growth (period-over-period / CAGR)
    revenue_growth: Mapped[float | None] = mapped_column(Numeric(12, 6))
    revenue_cagr_3y: Mapped[float | None] = mapped_column(Numeric(12, 6))
    eps_growth: Mapped[float | None] = mapped_column(Numeric(12, 6))
    eps_cagr_3y: Mapped[float | None] = mapped_column(Numeric(12, 6))

    # Leverage / liquidity
    debt_to_equity: Mapped[float | None] = mapped_column(Numeric(12, 6))
    current_ratio: Mapped[float | None] = mapped_column(Numeric(12, 6))
    quick_ratio: Mapped[float | None] = mapped_column(Numeric(12, 6))
    interest_coverage: Mapped[float | None] = mapped_column(Numeric(12, 6))

    # Valuation
    pe_ratio: Mapped[float | None] = mapped_column(Numeric(12, 6))
    peg_ratio: Mapped[float | None] = mapped_column(Numeric(12, 6))
    price_to_sales: Mapped[float | None] = mapped_column(Numeric(12, 6))
    price_to_book: Mapped[float | None] = mapped_column(Numeric(12, 6))
    ev_to_ebitda: Mapped[float | None] = mapped_column(Numeric(12, 6))
    enterprise_value: Mapped[float | None] = mapped_column(Numeric(24, 4))
    book_value_per_share: Mapped[float | None] = mapped_column(Numeric(20, 6))

    # Dividends
    dividend_yield: Mapped[float | None] = mapped_column(Numeric(12, 6))
    payout_ratio: Mapped[float | None] = mapped_column(Numeric(12, 6))
    dividend_growth: Mapped[float | None] = mapped_column(Numeric(12, 6))

    # Composite health scores
    altman_z: Mapped[float | None] = mapped_column(Numeric(12, 6))
    piotroski_f: Mapped[int | None] = mapped_column(Integer)


class FundamentalSnapshot(Base, TimestampMixin):
    """Latest-known fundamental headline metrics, one row per security.

    A denormalised convenience row the screener reads without touching the full
    statement history. Refreshed by the fundamental engine.
    """

    __tablename__ = "fundamental_snapshots"

    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE"), primary_key=True
    )
    as_of: Mapped[date | None] = mapped_column(Date)

    pe_ttm: Mapped[float | None] = mapped_column(Numeric(12, 6))
    roe: Mapped[float | None] = mapped_column(Numeric(12, 6))
    debt_to_equity: Mapped[float | None] = mapped_column(Numeric(12, 6))
    revenue_growth: Mapped[float | None] = mapped_column(Numeric(12, 6))
    eps_growth: Mapped[float | None] = mapped_column(Numeric(12, 6))
    net_margin: Mapped[float | None] = mapped_column(Numeric(12, 6))
    dividend_yield: Mapped[float | None] = mapped_column(Numeric(12, 6))
    market_cap: Mapped[float | None] = mapped_column(Numeric(24, 2))


class AnalystEstimate(Base, TimestampMixin):
    __tablename__ = "analyst_estimates"
    __table_args__ = (
        UniqueConstraint(
            "security_id", "fiscal_date", name="uq_estimate_sec_date"
        ),
        Index("ix_estimate_security_date", "security_id", "fiscal_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE"), nullable=False
    )
    fiscal_date: Mapped[date] = mapped_column(Date, nullable=False)

    estimated_revenue: Mapped[float | None] = mapped_column(Numeric(24, 4))
    estimated_eps: Mapped[float | None] = mapped_column(Numeric(20, 6))
    analyst_count: Mapped[int | None] = mapped_column(Integer)
    target_price_mean: Mapped[float | None] = mapped_column(Numeric(20, 6))
    target_price_high: Mapped[float | None] = mapped_column(Numeric(20, 6))
    target_price_low: Mapped[float | None] = mapped_column(Numeric(20, 6))
    rating_mean: Mapped[float | None] = mapped_column(Numeric(6, 3))  # 1=buy … 5=sell
