"""Market and security schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.models.enums import AssetClass, MarketRegion


class MarketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    region: MarketRegion
    country: str | None
    currency: str
    ticker_suffix: str
    is_active: bool


class SecurityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    provider_symbol: str
    name: str | None
    asset_class: AssetClass
    sector: str | None
    industry: str | None
    currency: str | None
    country: str | None
    market_cap: float | None
    is_active: bool
