"""Analytics output: composite scores and actionable signals.

Every score row carries a ``breakdown`` JSON documenting exactly which inputs and
weights produced it — this is what makes scores explainable and auditable, and is
the direct antidote to the legacy ``random.randint`` scoring.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Date,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import SignalType

if TYPE_CHECKING:
    from app.models.market import Security

# JSONB on Postgres, plain JSON elsewhere (tests on SQLite).
JSONType = JSON().with_variant(JSONB, "postgresql")


class Score(Base, TimestampMixin):
    """A dated composite score with its five components and breakdown.

    Unique per ``(security_id, as_of)`` so the table doubles as the historical
    score series consumed by the company page.
    """

    __tablename__ = "scores"
    __table_args__ = (
        UniqueConstraint("security_id", "as_of", name="uq_scores_security_asof"),
        Index("ix_scores_security_asof", "security_id", "as_of"),
        Index("ix_scores_composite", "composite"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE"), nullable=False
    )
    as_of: Mapped[date] = mapped_column(Date, nullable=False)

    # Each 0..100, or NULL when there is insufficient data to compute honestly.
    fundamental: Mapped[float | None] = mapped_column(Numeric(6, 2))
    technical: Mapped[float | None] = mapped_column(Numeric(6, 2))
    momentum: Mapped[float | None] = mapped_column(Numeric(6, 2))
    quality: Mapped[float | None] = mapped_column(Numeric(6, 2))
    risk: Mapped[float | None] = mapped_column(Numeric(6, 2))
    composite: Mapped[float | None] = mapped_column(Numeric(6, 2))

    # {"fundamental": {"inputs": {...}, "weight": 0.35, "contribution": ...}, ...}
    breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSONType)

    security: Mapped[Security] = relationship(back_populates="scores")


class Signal(Base, TimestampMixin):
    """A dated actionable rating derived from the composite score + rules."""

    __tablename__ = "signals"
    __table_args__ = (
        UniqueConstraint("security_id", "as_of", name="uq_signals_security_asof"),
        Index("ix_signals_security_asof", "security_id", "as_of"),
        Index("ix_signals_type", "signal_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE"), nullable=False
    )
    as_of: Mapped[date] = mapped_column(Date, nullable=False)

    signal_type: Mapped[SignalType] = mapped_column(Enum(SignalType, native_enum=False))
    confidence: Mapped[float | None] = mapped_column(Numeric(6, 4))  # 0..1
    rationale: Mapped[str | None] = mapped_column(Text)
    triggers: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    label: Mapped[str | None] = mapped_column(String(64))  # short UI badge text
