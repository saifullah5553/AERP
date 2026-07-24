"""Country macro-economic indicators — the 'fundamentals' for forex."""

from __future__ import annotations

from datetime import date

from sqlalchemy import (
    Date,
    Enum,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enums import MacroIndicatorType


class MacroIndicator(Base, TimestampMixin):
    __tablename__ = "macro_indicators"
    __table_args__ = (
        UniqueConstraint(
            "country", "indicator", "period_date", name="uq_macro_country_ind_date"
        ),
        Index("ix_macro_country_indicator", "country", "indicator", "period_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    country: Mapped[str] = mapped_column(String(3), nullable=False)  # ISO-2 or WB code (EMU)
    indicator: Mapped[MacroIndicatorType] = mapped_column(
        Enum(MacroIndicatorType, native_enum=False)
    )
    period_date: Mapped[date] = mapped_column(Date, nullable=False)  # year-end
    value: Mapped[float | None] = mapped_column(Numeric(20, 6))
    source: Mapped[str] = mapped_column(String(32), default="worldbank", nullable=False)
