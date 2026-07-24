"""Price time-series: daily OHLCV and intraday bars."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import Timeframe
from app.models.market import Security


class DailyPrice(Base, TimestampMixin):
    """One end-of-day OHLCV bar per security per trading day."""

    __tablename__ = "daily_prices"
    __table_args__ = (
        UniqueConstraint("security_id", "date", name="uq_daily_prices_security_date"),
        Index("ix_daily_prices_security_date", "security_id", "date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)

    open: Mapped[float | None] = mapped_column(Numeric(20, 6))
    high: Mapped[float | None] = mapped_column(Numeric(20, 6))
    low: Mapped[float | None] = mapped_column(Numeric(20, 6))
    close: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    # Split/dividend-adjusted close for return calculations.
    adj_close: Mapped[float | None] = mapped_column(Numeric(20, 6))
    volume: Mapped[int | None] = mapped_column(BigInteger)

    security: Mapped[Security] = relationship(back_populates="daily_prices")


class IntradayPrice(Base):
    """Intraday bars. Timeframe-tagged so a single table serves 1m…1h."""

    __tablename__ = "intraday_prices"
    __table_args__ = (
        UniqueConstraint(
            "security_id", "timeframe", "ts", name="uq_intraday_security_tf_ts"
        ),
        Index("ix_intraday_security_tf_ts", "security_id", "timeframe", "ts"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE"), nullable=False
    )
    timeframe: Mapped[Timeframe] = mapped_column(Enum(Timeframe, native_enum=False))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    open: Mapped[float | None] = mapped_column(Numeric(20, 6))
    high: Mapped[float | None] = mapped_column(Numeric(20, 6))
    low: Mapped[float | None] = mapped_column(Numeric(20, 6))
    close: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    volume: Mapped[int | None] = mapped_column(BigInteger)
