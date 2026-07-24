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
