"""Reference tables: markets and securities."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import AssetClass, MarketRegion

if TYPE_CHECKING:
    from app.models.prices import DailyPrice
    from app.models.scoring import Score


class Market(Base, TimestampMixin):
    """A tradable exchange/venue (e.g. NASDAQ, PSX, Binance, FX)."""

    __tablename__ = "markets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)  # e.g. "NASDAQ"
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    region: Mapped[MarketRegion] = mapped_column(Enum(MarketRegion, native_enum=False))
    country: Mapped[str | None] = mapped_column(String(2))  # ISO-3166 alpha-2
    currency: Mapped[str] = mapped_column(String(8), nullable=False)  # ISO-4217 or "USDT"
    timezone: Mapped[str | None] = mapped_column(String(64))
    # Yahoo/provider suffix, e.g. ".KA" for PSX, ".NS" for NSE, "" for US.
    ticker_suffix: Mapped[str] = mapped_column(String(8), default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    securities: Mapped[list[Security]] = relationship(back_populates="market")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Market {self.code}>"


class Security(Base, TimestampMixin):
    """A single tradable instrument. The hub the rest of the schema hangs off."""

    __tablename__ = "securities"
    __table_args__ = (
        UniqueConstraint("market_id", "symbol", name="uq_securities_market_symbol"),
        Index("ix_securities_asset_class", "asset_class"),
        Index("ix_securities_sector", "sector"),
        Index("ix_securities_is_active", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market_id: Mapped[int] = mapped_column(
        ForeignKey("markets.id", ondelete="CASCADE"), index=True, nullable=False
    )

    # Exchange-local symbol, e.g. "AAPL", "LUCK", "RELIANCE".
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    # Fully-qualified provider symbol, e.g. "LUCK.KA", "RELIANCE.NS", "BTC-USD".
    provider_symbol: Mapped[str] = mapped_column(String(48), index=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(256))
    asset_class: Mapped[AssetClass] = mapped_column(Enum(AssetClass, native_enum=False))

    sector: Mapped[str | None] = mapped_column(String(128))
    industry: Mapped[str | None] = mapped_column(String(128))
    currency: Mapped[str | None] = mapped_column(String(8))
    country: Mapped[str | None] = mapped_column(String(2))
    isin: Mapped[str | None] = mapped_column(String(12), index=True)
    figi: Mapped[str | None] = mapped_column(String(12))
    cik: Mapped[str | None] = mapped_column(String(10), index=True)  # SEC EDGAR id

    # Fast-read cached snapshot (kept in sync by ingestion; DB stays source of truth).
    market_cap: Mapped[float | None] = mapped_column(Numeric(24, 2))
    shares_outstanding: Mapped[float | None] = mapped_column(Numeric(24, 2))

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    market: Mapped[Market] = relationship(back_populates="securities")
    daily_prices: Mapped[list[DailyPrice]] = relationship(
        back_populates="security", cascade="all, delete-orphan", passive_deletes=True
    )
    scores: Mapped[list[Score]] = relationship(
        back_populates="security", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Security {self.provider_symbol}>"
