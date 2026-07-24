"""Market intelligence: news articles and the economic calendar."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class NewsArticle(Base, TimestampMixin):
    """A news item. ``security_id`` is nullable for market-wide/macro news."""

    __tablename__ = "news_articles"
    __table_args__ = (
        Index("ix_news_security_published", "security_id", "published_at"),
        Index("ix_news_published", "published_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    security_id: Mapped[int | None] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE")
    )
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str | None] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    url: Mapped[str | None] = mapped_column(String(1024))
    summary: Mapped[str | None] = mapped_column(Text)
    # -1..1 sentiment (populated by an NLP pass in a later phase).
    sentiment: Mapped[float | None] = mapped_column(Numeric(5, 4))
    # De-dupe key (hash of url/title) to avoid storing the same story twice.
    dedupe_hash: Mapped[str | None] = mapped_column(String(64), unique=True)


class EconomicEvent(Base, TimestampMixin):
    """A macro-economic calendar entry (rate decisions, CPI, NFP, …)."""

    __tablename__ = "economic_events"
    __table_args__ = (
        Index("ix_econ_event_time", "event_time"),
        Index("ix_econ_event_country", "country"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    country: Mapped[str | None] = mapped_column(String(2))
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    importance: Mapped[str | None] = mapped_column(String(16))  # low / medium / high
    actual: Mapped[str | None] = mapped_column(String(64))
    forecast: Mapped[str | None] = mapped_column(String(64))
    previous: Mapped[str | None] = mapped_column(String(64))
