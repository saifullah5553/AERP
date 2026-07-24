"""Company detail response schema."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel


class ScorePoint(BaseModel):
    as_of: date
    composite: float | None = None
    fundamental: float | None = None
    technical: float | None = None
    momentum: float | None = None
    quality: float | None = None
    risk: float | None = None


class PeerOut(BaseModel):
    provider_symbol: str
    symbol: str
    name: str | None
    sector: str | None
    composite_score: float | None
    price: float | None


class CompanyDetail(BaseModel):
    # Identity / market
    security: dict[str, Any]
    tradingview_symbol: str | None

    # Live + latest analytics
    quote: dict[str, Any] | None
    scores: dict[str, Any] | None       # latest scores row incl. breakdown
    signal: dict[str, Any] | None
    fundamentals: dict[str, Any] | None  # snapshot headline metrics
    ratios: dict[str, Any] | None        # latest FinancialRatios
    technical: dict[str, Any] | None     # latest TechnicalIndicator

    # Collections
    statements: dict[str, list[dict[str, Any]]]  # {income, balance, cashflow}
    patterns: list[dict[str, Any]]
    score_history: list[ScorePoint]
    dividends: list[dict[str, Any]]
    estimates: list[dict[str, Any]]
    peers: list[PeerOut]
    news: list[dict[str, Any]]
    insider: list[dict[str, Any]]
    insider_summary: dict[str, Any] | None

    ai_summary: str
