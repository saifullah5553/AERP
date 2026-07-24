"""The main screener endpoint — the professional data table replacing cards."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import Pagination, pagination_params
from app.db.session import get_db
from app.models.enums import AssetClass, MarketRegion
from app.schemas.common import Page
from app.schemas.screener import ScreenerColumn, ScreenerRow
from app.services.screener import SORT_FIELDS, ScreenerFilters, query_screener

router = APIRouter(prefix="/screener", tags=["screener"])

# Column contract the frontend grid uses to self-configure.
COLUMNS: list[ScreenerColumn] = [
    ScreenerColumn(field="symbol", header="Ticker", type="string"),
    ScreenerColumn(field="name", header="Company", type="string"),
    ScreenerColumn(field="market_code", header="Exchange", type="string"),
    ScreenerColumn(field="sector", header="Sector", type="string"),
    ScreenerColumn(field="industry", header="Industry", type="string"),
    ScreenerColumn(field="price", header="Price", type="currency"),
    ScreenerColumn(field="change_pct", header="Change %", type="percent"),
    ScreenerColumn(field="volume", header="Volume", type="number"),
    ScreenerColumn(field="market_cap", header="Market Cap", type="currency"),
    ScreenerColumn(field="pe_ttm", header="P/E", type="number"),
    ScreenerColumn(field="roe", header="ROE", type="percent"),
    ScreenerColumn(field="debt_to_equity", header="Debt/Eq", type="number"),
    ScreenerColumn(field="revenue_growth", header="Rev Growth", type="percent"),
    ScreenerColumn(field="eps_growth", header="EPS Growth", type="percent"),
    ScreenerColumn(field="dividend_yield", header="Div Yield", type="percent"),
    ScreenerColumn(field="technical_score", header="Technical", type="score"),
    ScreenerColumn(field="fundamental_score", header="Fundamental", type="score"),
    ScreenerColumn(field="composite_score", header="Composite", type="score"),
    ScreenerColumn(field="top_pattern", header="Pattern", type="string"),
    ScreenerColumn(field="insider_score", header="Insider", type="score",
                   description="60-day insider buy/sell score (100=buying, 0=selling)"),
    ScreenerColumn(field="insider_activity", header="Insider Act.", type="string"),
    ScreenerColumn(field="signal", header="Signal", type="enum"),
]


@router.get("/columns", response_model=list[ScreenerColumn], summary="Grid columns")
def screener_columns() -> list[ScreenerColumn]:
    return COLUMNS


@router.get("", response_model=Page[ScreenerRow], summary="Run the screener")
def run_screener(
    db: Session = Depends(get_db),
    pagination: Pagination = Depends(pagination_params),
    search: str | None = Query(None, description="Match ticker or company name"),
    region: MarketRegion | None = Query(None),
    asset_class: AssetClass | None = Query(None),
    market_code: str | None = Query(None),
    sector: str | None = Query(None),
    min_composite: float | None = Query(None, ge=0, le=100),
    max_composite: float | None = Query(None, ge=0, le=100),
    min_price: float | None = Query(None, ge=0),
    max_price: float | None = Query(None, ge=0),
    min_market_cap: float | None = Query(None, ge=0),
    sort_by: str = Query("composite_score", description=f"One of: {', '.join(SORT_FIELDS)}"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
) -> Page[ScreenerRow]:
    filters = ScreenerFilters(
        search=search,
        region=region,
        asset_class=asset_class,
        market_code=market_code,
        sector=sector,
        min_composite=min_composite,
        max_composite=max_composite,
        min_price=min_price,
        max_price=max_price,
        min_market_cap=min_market_cap,
        sort_by=sort_by if sort_by in SORT_FIELDS else "composite_score",
        sort_dir=sort_dir,
    )
    rows, total = query_screener(db, filters, pagination.offset, pagination.limit)
    return Page[ScreenerRow](
        items=rows,
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )
