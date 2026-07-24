"""Screener query service.

Builds the flat screener rows by joining the security hub to its latest quote,
fundamental snapshot, composite score, and signal. All external-data joins are
LEFT joins so a security with no price/score yet still appears (with NULLs) rather
than vanishing — honesty over hiding gaps.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models.enums import AssetClass, MarketRegion
from app.models.fundamentals import FundamentalSnapshot
from app.models.market import Market, Security
from app.models.quote import Quote
from app.models.scoring import Score, Signal
from app.models.technical import PatternDetection
from app.schemas.screener import ScreenerRow

# Whitelist of sortable fields → SQL expressions. Anything else is rejected.
SORT_FIELDS = {
    "symbol": Security.symbol,
    "name": Security.name,
    "market_cap": Security.market_cap,
    "price": Quote.price,
    "change_pct": Quote.change_pct,
    "volume": Quote.volume,
    "pe_ttm": FundamentalSnapshot.pe_ttm,
    "roe": FundamentalSnapshot.roe,
    "debt_to_equity": FundamentalSnapshot.debt_to_equity,
    "revenue_growth": FundamentalSnapshot.revenue_growth,
    "eps_growth": FundamentalSnapshot.eps_growth,
    "dividend_yield": FundamentalSnapshot.dividend_yield,
    "fundamental_score": Score.fundamental,
    "technical_score": Score.technical,
    "composite_score": Score.composite,
}


@dataclass
class ScreenerFilters:
    search: str | None = None
    region: MarketRegion | None = None
    asset_class: AssetClass | None = None
    market_code: str | None = None
    sector: str | None = None
    min_composite: float | None = None
    max_composite: float | None = None
    min_price: float | None = None
    max_price: float | None = None
    min_market_cap: float | None = None
    sort_by: str = "composite_score"
    sort_dir: str = "desc"


def _latest_subqueries():
    """Subqueries selecting the most-recent (security_id, as_of) for scores/signals."""
    latest_score = (
        select(Score.security_id, func.max(Score.as_of).label("as_of"))
        .group_by(Score.security_id)
        .subquery("latest_score")
    )
    latest_signal = (
        select(Signal.security_id, func.max(Signal.as_of).label("as_of"))
        .group_by(Signal.security_id)
        .subquery("latest_signal")
    )
    return latest_score, latest_signal


def _top_pattern_subquery():
    """Highest-confidence active pattern per security (rn == 1)."""
    ranked = (
        select(
            PatternDetection.security_id.label("security_id"),
            PatternDetection.name.label("name"),
            func.row_number()
            .over(
                partition_by=PatternDetection.security_id,
                order_by=[
                    PatternDetection.confidence.desc(),
                    PatternDetection.detected_on.desc(),
                ],
            )
            .label("rn"),
        )
        .where(PatternDetection.is_active.is_(True))
        .subquery("ranked_patterns")
    )
    return select(ranked.c.security_id, ranked.c.name).where(ranked.c.rn == 1).subquery(
        "top_pattern"
    )


def _base_select() -> Select:
    latest_score, latest_signal = _latest_subqueries()
    top_pattern = _top_pattern_subquery()

    return (
        select(
            Security.id.label("security_id"),
            Security.symbol,
            Security.provider_symbol,
            Security.name,
            Market.code.label("market_code"),
            Market.region,
            Security.asset_class,
            Security.sector,
            Security.industry,
            Security.currency,
            Quote.price,
            Quote.change,
            Quote.change_pct,
            Quote.volume,
            Security.market_cap,
            FundamentalSnapshot.pe_ttm,
            FundamentalSnapshot.roe,
            FundamentalSnapshot.debt_to_equity,
            FundamentalSnapshot.revenue_growth,
            FundamentalSnapshot.eps_growth,
            FundamentalSnapshot.dividend_yield,
            Score.fundamental.label("fundamental_score"),
            Score.technical.label("technical_score"),
            Score.composite.label("composite_score"),
            Score.as_of.label("scored_on"),
            Signal.signal_type.label("signal"),
            Signal.label.label("signal_label"),
            top_pattern.c.name.label("top_pattern"),
        )
        .join(Market, Security.market_id == Market.id)
        .outerjoin(top_pattern, top_pattern.c.security_id == Security.id)
        .outerjoin(Quote, Quote.security_id == Security.id)
        .outerjoin(FundamentalSnapshot, FundamentalSnapshot.security_id == Security.id)
        .outerjoin(
            latest_score,
            latest_score.c.security_id == Security.id,
        )
        .outerjoin(
            Score,
            (Score.security_id == Security.id)
            & (Score.as_of == latest_score.c.as_of),
        )
        .outerjoin(
            latest_signal,
            latest_signal.c.security_id == Security.id,
        )
        .outerjoin(
            Signal,
            (Signal.security_id == Security.id)
            & (Signal.as_of == latest_signal.c.as_of),
        )
        .where(Security.is_active.is_(True))
    )


def _apply_filters(stmt: Select, f: ScreenerFilters) -> Select:
    if f.search:
        term = f"%{f.search.strip()}%"
        stmt = stmt.where(
            Security.symbol.ilike(term) | Security.name.ilike(term)
        )
    if f.region is not None:
        stmt = stmt.where(Market.region == f.region)
    if f.asset_class is not None:
        stmt = stmt.where(Security.asset_class == f.asset_class)
    if f.market_code:
        stmt = stmt.where(Market.code == f.market_code)
    if f.sector:
        stmt = stmt.where(Security.sector == f.sector)
    if f.min_composite is not None:
        stmt = stmt.where(Score.composite >= f.min_composite)
    if f.max_composite is not None:
        stmt = stmt.where(Score.composite <= f.max_composite)
    if f.min_price is not None:
        stmt = stmt.where(Quote.price >= f.min_price)
    if f.max_price is not None:
        stmt = stmt.where(Quote.price <= f.max_price)
    if f.min_market_cap is not None:
        stmt = stmt.where(Security.market_cap >= f.min_market_cap)
    return stmt


def query_screener(
    db: Session, filters: ScreenerFilters, offset: int, limit: int
) -> tuple[list[ScreenerRow], int]:
    stmt = _apply_filters(_base_select(), filters)

    # Total count over the filtered set (before pagination).
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    # Ordering: whitelisted column, NULLs always last, stable tiebreak on symbol.
    sort_col = SORT_FIELDS.get(filters.sort_by, Score.composite)
    ordering = sort_col.desc() if filters.sort_dir == "desc" else sort_col.asc()
    stmt = stmt.order_by(ordering.nulls_last(), Security.symbol.asc())

    rows = db.execute(stmt.offset(offset).limit(limit)).mappings().all()

    result = [
        ScreenerRow(
            security_id=r["security_id"],
            symbol=r["symbol"],
            provider_symbol=r["provider_symbol"],
            name=r["name"],
            market_code=r["market_code"],
            region=r["region"],
            asset_class=r["asset_class"],
            sector=r["sector"],
            industry=r["industry"],
            currency=r["currency"],
            price=_f(r["price"]),
            change=_f(r["change"]),
            change_pct=_f(r["change_pct"]),
            volume=r["volume"],
            market_cap=_f(r["market_cap"]),
            pe_ttm=_f(r["pe_ttm"]),
            roe=_f(r["roe"]),
            debt_to_equity=_f(r["debt_to_equity"]),
            revenue_growth=_f(r["revenue_growth"]),
            eps_growth=_f(r["eps_growth"]),
            dividend_yield=_f(r["dividend_yield"]),
            fundamental_score=_f(r["fundamental_score"]),
            technical_score=_f(r["technical_score"]),
            composite_score=_f(r["composite_score"]),
            signal=r["signal"],
            signal_label=r["signal_label"],
            top_pattern=r["top_pattern"],
            scored_on=r["scored_on"],
        )
        for r in rows
    ]
    return result, total


def _f(value) -> float | None:
    """Coerce SQL ``Numeric`` (Decimal) to float for JSON, preserving NULL."""
    return float(value) if value is not None else None
