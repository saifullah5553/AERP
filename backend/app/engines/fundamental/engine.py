"""Fundamental engine orchestration.

Reads a security's stored annual statements, computes ratios + Piotroski F +
Altman Z, derives the weighted 0–100 fundamental score, and persists:

- ``financial_ratios``      — one row per reporting period (audit trail)
- ``fundamental_snapshots`` — denormalised headline metrics for the screener
- ``scores``                — the fundamental component + its breakdown (as_of today)

Nothing here calls a data provider; it operates purely on data already ingested.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.engines.common import f
from app.engines.fundamental.health import altman_z_score, piotroski_f_score
from app.engines.fundamental.ratios import MarketInputs, RatioSet, compute_ratios
from app.engines.fundamental.scoring import score_fundamentals
from app.models.enums import StatementPeriod
from app.models.fundamentals import (
    BalanceSheet,
    CashFlowStatement,
    FinancialRatios,
    FundamentalSnapshot,
    IncomeStatement,
)
from app.models.market import Security
from app.models.quote import Quote
from app.models.scoring import Score

log = get_logger(__name__)

# RatioSet attribute → FinancialRatios column (only names that exist on both).
_RATIO_COLUMNS = [
    "gross_margin", "operating_margin", "net_margin", "roe", "roa", "roic",
    "revenue_growth", "revenue_cagr_3y", "eps_growth", "eps_cagr_3y",
    "debt_to_equity", "current_ratio", "quick_ratio", "interest_coverage",
    "pe_ratio", "peg_ratio", "price_to_sales", "price_to_book", "ev_to_ebitda",
    "enterprise_value", "book_value_per_share", "dividend_yield", "payout_ratio",
    "dividend_growth", "altman_z", "piotroski_f",
]


@dataclass(slots=True)
class FundamentalOutcome:
    security_id: int
    score: float | None
    coverage: float
    computed: bool


def _annual(db: Session, model, security_id: int) -> list:
    return list(
        db.scalars(
            select(model)
            .where(model.security_id == security_id, model.period == StatementPeriod.ANNUAL)
            .order_by(model.fiscal_date.asc())
        )
    )


def compute_for_security(db: Session, security: Security) -> FundamentalOutcome:
    incomes = _annual(db, IncomeStatement, security.id)
    balances = _annual(db, BalanceSheet, security.id)
    cashflows = _annual(db, CashFlowStatement, security.id)

    if not incomes or not balances:
        return FundamentalOutcome(security.id, None, 0.0, computed=False)

    quote = db.get(Quote, security.id)
    market = MarketInputs(
        price=f(quote.price) if quote else None,
        shares_outstanding=f(security.shares_outstanding),
        market_cap=f(security.market_cap),
    )

    ratios: RatioSet = compute_ratios(incomes, balances, cashflows, market)
    piotroski = piotroski_f_score(incomes, balances, cashflows)
    ratios.piotroski_f = piotroski.score
    ratios.altman_z = altman_z_score(incomes[-1], balances[-1], market.resolved_market_cap())

    metrics = {
        "roe": ratios.roe,
        "net_margin": ratios.net_margin,
        "roa": ratios.roa,
        "gross_margin": ratios.gross_margin,
        "revenue_growth": ratios.revenue_growth,
        "eps_growth": ratios.eps_growth,
        "debt_to_equity": ratios.debt_to_equity,
        "current_ratio": ratios.current_ratio,
        "interest_coverage": ratios.interest_coverage,
        "fcf_margin": ratios.fcf_margin,
        "piotroski_f": float(ratios.piotroski_f) if ratios.piotroski_f is not None else None,
        "altman_z": ratios.altman_z,
    }
    result = score_fundamentals(metrics)
    fiscal_date = incomes[-1].fiscal_date

    _persist_ratios(db, security.id, fiscal_date, ratios)
    _persist_snapshot(db, security.id, fiscal_date, ratios, market)
    _persist_score(db, security.id, result.score, result.breakdown, piotroski.criteria)
    db.commit()

    return FundamentalOutcome(security.id, result.score, result.coverage, computed=True)


def compute_all(db: Session, limit: int | None = None) -> dict[str, int]:
    """Compute fundamentals for every security that has statements."""
    sec_ids = db.scalars(
        select(IncomeStatement.security_id)
        .where(IncomeStatement.period == StatementPeriod.ANNUAL)
        .distinct()
    ).all()
    if limit is not None:
        sec_ids = sec_ids[:limit]

    scored = 0
    for sid in sec_ids:
        security = db.get(Security, sid)
        if security is None:
            continue
        outcome = compute_for_security(db, security)
        if outcome.computed and outcome.score is not None:
            scored += 1
    result = {"securities": len(sec_ids), "scored": scored}
    log.info("compute_all fundamentals: %s", result)
    return result


# ── Persistence ───────────────────────────────────────────────
def _persist_ratios(db: Session, security_id: int, fiscal_date: date, ratios: RatioSet) -> None:
    row = db.scalar(
        select(FinancialRatios).where(
            FinancialRatios.security_id == security_id,
            FinancialRatios.period == StatementPeriod.ANNUAL,
            FinancialRatios.fiscal_date == fiscal_date,
        )
    )
    if row is None:
        row = FinancialRatios(
            security_id=security_id, period=StatementPeriod.ANNUAL, fiscal_date=fiscal_date
        )
        db.add(row)
    for col in _RATIO_COLUMNS:
        setattr(row, col, getattr(ratios, col))


def _persist_snapshot(
    db: Session, security_id: int, fiscal_date: date, ratios: RatioSet, market: MarketInputs
) -> None:
    snap = db.get(FundamentalSnapshot, security_id)
    if snap is None:
        snap = FundamentalSnapshot(security_id=security_id)
        db.add(snap)
    snap.as_of = fiscal_date
    snap.pe_ttm = ratios.pe_ratio
    snap.roe = ratios.roe
    snap.debt_to_equity = ratios.debt_to_equity
    snap.revenue_growth = ratios.revenue_growth
    snap.eps_growth = ratios.eps_growth
    snap.net_margin = ratios.net_margin
    snap.dividend_yield = ratios.dividend_yield
    snap.market_cap = market.resolved_market_cap()


def _persist_score(
    db: Session,
    security_id: int,
    score: float | None,
    breakdown: dict,
    criteria: dict,
) -> None:
    today = date.today()
    row = db.scalar(
        select(Score).where(Score.security_id == security_id, Score.as_of == today)
    )
    if row is None:
        row = Score(security_id=security_id, as_of=today)
        db.add(row)
    row.fundamental = score
    # Merge into any existing breakdown so a same-day technical run is preserved.
    merged = dict(row.breakdown or {})
    merged["fundamental"] = {**breakdown, "piotroski_criteria": criteria}
    row.breakdown = merged
