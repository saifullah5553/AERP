"""Technical analysis output: indicator snapshots and detected patterns."""

from __future__ import annotations

from datetime import date

from sqlalchemy import (
    Boolean,
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
from app.models.enums import PatternCategory, PatternDirection, Timeframe


class TechnicalIndicator(Base, TimestampMixin):
    """Latest indicator values per security per timeframe (technical engine output)."""

    __tablename__ = "technical_indicators"
    __table_args__ = (
        UniqueConstraint(
            "security_id", "timeframe", "date", name="uq_tech_sec_tf_date"
        ),
        Index("ix_tech_security_tf_date", "security_id", "timeframe", "date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE"), nullable=False
    )
    timeframe: Mapped[Timeframe] = mapped_column(Enum(Timeframe, native_enum=False))
    date: Mapped[date] = mapped_column(Date, nullable=False)

    # Moving averages
    sma_20: Mapped[float | None] = mapped_column(Numeric(20, 6))
    sma_50: Mapped[float | None] = mapped_column(Numeric(20, 6))
    sma_200: Mapped[float | None] = mapped_column(Numeric(20, 6))
    ema_12: Mapped[float | None] = mapped_column(Numeric(20, 6))
    ema_26: Mapped[float | None] = mapped_column(Numeric(20, 6))
    ema_50: Mapped[float | None] = mapped_column(Numeric(20, 6))

    # Oscillators / trend
    rsi_14: Mapped[float | None] = mapped_column(Numeric(12, 6))
    macd: Mapped[float | None] = mapped_column(Numeric(20, 6))
    macd_signal: Mapped[float | None] = mapped_column(Numeric(20, 6))
    macd_hist: Mapped[float | None] = mapped_column(Numeric(20, 6))
    adx_14: Mapped[float | None] = mapped_column(Numeric(12, 6))
    atr_14: Mapped[float | None] = mapped_column(Numeric(20, 6))
    supertrend: Mapped[float | None] = mapped_column(Numeric(20, 6))
    supertrend_dir: Mapped[int | None] = mapped_column(Integer)  # +1 up, -1 down

    # Ichimoku
    ichimoku_conversion: Mapped[float | None] = mapped_column(Numeric(20, 6))
    ichimoku_base: Mapped[float | None] = mapped_column(Numeric(20, 6))
    ichimoku_span_a: Mapped[float | None] = mapped_column(Numeric(20, 6))
    ichimoku_span_b: Mapped[float | None] = mapped_column(Numeric(20, 6))

    # Volume / flow
    vwap: Mapped[float | None] = mapped_column(Numeric(20, 6))
    obv: Mapped[float | None] = mapped_column(Numeric(24, 2))
    mfi_14: Mapped[float | None] = mapped_column(Numeric(12, 6))

    # Bands / channels
    bb_upper: Mapped[float | None] = mapped_column(Numeric(20, 6))
    bb_middle: Mapped[float | None] = mapped_column(Numeric(20, 6))
    bb_lower: Mapped[float | None] = mapped_column(Numeric(20, 6))
    keltner_upper: Mapped[float | None] = mapped_column(Numeric(20, 6))
    keltner_lower: Mapped[float | None] = mapped_column(Numeric(20, 6))
    donchian_upper: Mapped[float | None] = mapped_column(Numeric(20, 6))
    donchian_lower: Mapped[float | None] = mapped_column(Numeric(20, 6))

    # Derived signals
    relative_strength: Mapped[float | None] = mapped_column(Numeric(12, 6))  # vs benchmark
    high_52w: Mapped[float | None] = mapped_column(Numeric(20, 6))
    low_52w: Mapped[float | None] = mapped_column(Numeric(20, 6))
    pct_from_52w_high: Mapped[float | None] = mapped_column(Numeric(12, 6))
    trend_strength: Mapped[float | None] = mapped_column(Numeric(12, 6))
    momentum: Mapped[float | None] = mapped_column(Numeric(12, 6))
    volatility: Mapped[float | None] = mapped_column(Numeric(12, 6))
    breakout_strength: Mapped[float | None] = mapped_column(Numeric(12, 6))


class PatternDetection(Base, TimestampMixin):
    """A single pattern instance detected on a security's chart."""

    __tablename__ = "pattern_detections"
    __table_args__ = (
        Index("ix_pattern_security_detected", "security_id", "detected_on"),
        Index("ix_pattern_name", "name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE"), nullable=False
    )
    timeframe: Mapped[Timeframe] = mapped_column(Enum(Timeframe, native_enum=False))
    detected_on: Mapped[date] = mapped_column(Date, nullable=False)

    name: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g. "cup_and_handle"
    category: Mapped[PatternCategory] = mapped_column(Enum(PatternCategory, native_enum=False))
    direction: Mapped[PatternDirection] = mapped_column(
        Enum(PatternDirection, native_enum=False)
    )
    confidence: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)  # 0..1
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Geometry / target levels for chart overlays and audit.
    start_date: Mapped[date | None] = mapped_column(Date)
    breakout_level: Mapped[float | None] = mapped_column(Numeric(20, 6))
    target_price: Mapped[float | None] = mapped_column(Numeric(20, 6))
    stop_level: Mapped[float | None] = mapped_column(Numeric(20, 6))
