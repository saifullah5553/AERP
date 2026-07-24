"""Corporate events: actions, dividends, insider transactions."""

from __future__ import annotations

from datetime import date

from sqlalchemy import (
    Date,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enums import CorporateActionType, InsiderTransactionType


class CorporateAction(Base, TimestampMixin):
    __tablename__ = "corporate_actions"
    __table_args__ = (
        Index("ix_corp_action_security_date", "security_id", "ex_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE"), nullable=False
    )
    action_type: Mapped[CorporateActionType] = mapped_column(
        Enum(CorporateActionType, native_enum=False)
    )
    ex_date: Mapped[date] = mapped_column(Date, nullable=False)
    record_date: Mapped[date | None] = mapped_column(Date)
    # e.g. split ratio 2.0 = 2-for-1; bonus 0.1 = 1 bonus share per 10 held.
    ratio: Mapped[float | None] = mapped_column(Numeric(12, 6))
    description: Mapped[str | None] = mapped_column(String(256))


class Dividend(Base, TimestampMixin):
    __tablename__ = "dividends"
    __table_args__ = (
        UniqueConstraint("security_id", "ex_date", name="uq_dividend_sec_exdate"),
        Index("ix_dividend_security_date", "security_id", "ex_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE"), nullable=False
    )
    ex_date: Mapped[date] = mapped_column(Date, nullable=False)
    payment_date: Mapped[date | None] = mapped_column(Date)
    record_date: Mapped[date | None] = mapped_column(Date)
    amount: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    currency: Mapped[str | None] = mapped_column(String(8))
    frequency: Mapped[str | None] = mapped_column(String(16))  # quarterly / annual …


class InsiderTransaction(Base, TimestampMixin):
    __tablename__ = "insider_transactions"
    __table_args__ = (
        Index("ix_insider_security_date", "security_id", "transaction_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE"), nullable=False
    )
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    insider_name: Mapped[str | None] = mapped_column(String(256))
    insider_title: Mapped[str | None] = mapped_column(String(128))
    transaction_type: Mapped[InsiderTransactionType] = mapped_column(
        Enum(InsiderTransactionType, native_enum=False)
    )
    shares: Mapped[float | None] = mapped_column(Numeric(24, 2))
    price: Mapped[float | None] = mapped_column(Numeric(20, 6))
    value: Mapped[float | None] = mapped_column(Numeric(24, 2))


class InsiderSummary(Base, TimestampMixin):
    """Rolling insider-activity summary per security (output of the insider engine).

    One row per security. ``activity`` is a plain-language label derived from the
    value-weighted buy/sell balance over the trailing window; ``score`` is 0–100
    (100 = heavy net buying, 0 = heavy net selling), or NULL when no open-market
    insider trades occurred in the window.
    """

    __tablename__ = "insider_summaries"

    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE"), primary_key=True
    )
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    window_days: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    buy_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sell_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    buy_value: Mapped[float | None] = mapped_column(Numeric(24, 2))
    sell_value: Mapped[float | None] = mapped_column(Numeric(24, 2))
    net_value: Mapped[float | None] = mapped_column(Numeric(24, 2))
    score: Mapped[float | None] = mapped_column(Numeric(6, 2))
    activity: Mapped[str] = mapped_column(String(20), default="no_activity", nullable=False)
