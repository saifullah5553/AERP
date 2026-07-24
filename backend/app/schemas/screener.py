"""Screener row schema — the flat, table-friendly shape the grid consumes.

Deliberately denormalised: one row carries identity, live price, headline
fundamentals, and the composite score/signal, so the frontend AG Grid binds
directly with no client-side joining.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from app.models.enums import AssetClass, MarketRegion, SignalType


class ScreenerRow(BaseModel):
    # Identity
    security_id: int
    symbol: str
    provider_symbol: str
    name: str | None
    market_code: str
    region: MarketRegion
    asset_class: AssetClass
    sector: str | None
    industry: str | None
    currency: str | None

    # Live price
    price: float | None
    change: float | None
    change_pct: float | None
    volume: int | None
    market_cap: float | None

    # Headline fundamentals (from the latest fundamental snapshot)
    pe_ttm: float | None
    roe: float | None
    debt_to_equity: float | None
    revenue_growth: float | None
    eps_growth: float | None
    dividend_yield: float | None

    # Analytics (from the latest score/signal)
    fundamental_score: float | None
    technical_score: float | None
    composite_score: float | None
    signal: SignalType | None
    signal_label: str | None
    top_pattern: str | None
    insider_score: float | None
    insider_activity: str | None
    scored_on: date | None


class ScreenerColumn(BaseModel):
    """Metadata describing a screener column, so the grid can self-configure."""

    field: str
    header: str
    type: str  # "string" | "number" | "percent" | "currency" | "score" | "enum"
    sortable: bool = True
    filterable: bool = True
    description: str | None = None
