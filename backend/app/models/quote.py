"""Latest live-quote snapshot — one row per security.

The screener grid and the live price feed both read this table. Ingestion (and, in
Phase 9, the live engine) upsert it. Keeping "latest price" denormalised here means
the screener never has to compute the most-recent ``daily_prices`` row per security
at query time.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Numeric,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Quote(Base):
    __tablename__ = "quotes"

    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE"), primary_key=True
    )
    price: Mapped[float | None] = mapped_column(Numeric(20, 6))
    prev_close: Mapped[float | None] = mapped_column(Numeric(20, 6))
    change: Mapped[float | None] = mapped_column(Numeric(20, 6))
    change_pct: Mapped[float | None] = mapped_column(Numeric(12, 6))
    day_open: Mapped[float | None] = mapped_column(Numeric(20, 6))
    day_high: Mapped[float | None] = mapped_column(Numeric(20, 6))
    day_low: Mapped[float | None] = mapped_column(Numeric(20, 6))
    volume: Mapped[int | None] = mapped_column(BigInteger)
    # When the quote was last observed from a provider.
    quoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
