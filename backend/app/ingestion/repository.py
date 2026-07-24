"""Idempotent persistence helpers for ingested data.

Upserts are written dialect-agnostically (select-then-write) so the same code runs
on PostgreSQL in production and SQLite in tests. Callers own the transaction.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.ingestion.providers.base import OHLCVBar, QuoteDTO, SecurityProfile, StatementDTO
from app.models.fundamentals import BalanceSheet, CashFlowStatement, IncomeStatement
from app.models.market import Market, Security
from app.models.prices import DailyPrice
from app.models.quote import Quote

_STATEMENT_MODELS = {
    "income": IncomeStatement,
    "balance": BalanceSheet,
    "cashflow": CashFlowStatement,
}

log = get_logger(__name__)


def upsert_quote(db: Session, security_id: int, dto: QuoteDTO) -> Quote:
    """Insert or update the latest-quote snapshot for a security."""
    quote = db.get(Quote, security_id)
    if quote is None:
        quote = Quote(security_id=security_id)
        db.add(quote)
    quote.price = dto.price
    quote.prev_close = dto.prev_close
    quote.change = dto.change
    quote.change_pct = dto.change_pct
    quote.day_open = dto.day_open
    quote.day_high = dto.day_high
    quote.day_low = dto.day_low
    quote.volume = dto.volume
    quote.quoted_at = dto.quoted_at or datetime.now(tz=None)
    return quote


def upsert_daily_bars(db: Session, security_id: int, bars: list[OHLCVBar]) -> int:
    """Insert missing daily bars and update changed ones. Returns rows written."""
    if not bars:
        return 0
    dates = [b.date for b in bars]
    existing = {
        dp.date: dp
        for dp in db.scalars(
            select(DailyPrice).where(
                DailyPrice.security_id == security_id,
                DailyPrice.date.in_(dates),
            )
        )
    }
    written = 0
    for bar in bars:
        row = existing.get(bar.date)
        if row is None:
            db.add(
                DailyPrice(
                    security_id=security_id,
                    date=bar.date,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    adj_close=bar.adj_close,
                    volume=bar.volume,
                )
            )
            written += 1
        else:
            row.open = bar.open
            row.high = bar.high
            row.low = bar.low
            row.close = bar.close
            row.adj_close = bar.adj_close
            row.volume = bar.volume
            written += 1
    return written


def upsert_security(
    db: Session,
    market: Market,
    profile: SecurityProfile,
) -> tuple[Security, bool]:
    """Insert a security from a discovered profile, or enrich an existing one.

    Returns ``(security, created)``. Existing securities keep their identity but
    gain any newly-known name/sector/industry.
    """
    security = db.scalar(
        select(Security).where(
            Security.market_id == market.id, Security.symbol == profile.symbol
        )
    )
    provider_symbol = f"{profile.symbol}{market.ticker_suffix}"

    if security is None:
        security = Security(
            market_id=market.id,
            symbol=profile.symbol,
            provider_symbol=provider_symbol,
            name=profile.name,
            asset_class=profile.asset_class,
            sector=profile.sector,
            industry=profile.industry,
            currency=profile.currency or market.currency,
            country=profile.country or market.country,
            market_cap=profile.market_cap,
            is_active=True,
        )
        db.add(security)
        return security, True

    # Enrich only empty fields; never overwrite curated data with a blank.
    if not security.name and profile.name:
        security.name = profile.name
    if not security.sector and profile.sector:
        security.sector = profile.sector
    if not security.industry and profile.industry:
        security.industry = profile.industry
    if profile.market_cap is not None:
        security.market_cap = profile.market_cap
    return security, False


def upsert_statements(db: Session, security_id: int, statements: list[StatementDTO]) -> int:
    """Insert or update financial statements keyed by (type, period, fiscal_date)."""
    written = 0
    for dto in statements:
        model = _STATEMENT_MODELS.get(dto.statement_type)
        if model is None:
            continue
        row = db.scalar(
            select(model).where(
                model.security_id == security_id,
                model.period == dto.period,
                model.fiscal_date == dto.fiscal_date,
            )
        )
        if row is None:
            row = model(
                security_id=security_id, period=dto.period, fiscal_date=dto.fiscal_date
            )
            db.add(row)
        row.reported_currency = dto.reported_currency
        for col, value in dto.values.items():
            if hasattr(row, col):
                setattr(row, col, value)
        written += 1
    return written


def markets_by_code(db: Session) -> dict[str, Market]:
    return {m.code: m for m in db.scalars(select(Market))}
