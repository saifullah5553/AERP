"""Technical engine orchestration.

Reads a security's stored daily OHLCV, computes the full indicator set, derives the
weighted 0–100 technical score, and persists:

- ``technical_indicators`` — latest indicator snapshot (timeframe 1d)
- ``scores``               — the technical component + breakdown (as_of today)

Operates purely on already-ingested prices; never calls a data provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.engines.technical.indicators import IndicatorSet, compute_indicators
from app.engines.technical.scoring import score_technical
from app.models.enums import Timeframe
from app.models.market import Security
from app.models.prices import DailyPrice
from app.models.scoring import Score
from app.models.technical import TechnicalIndicator

log = get_logger(__name__)

MIN_BARS = 20  # below this almost nothing computes; skip

# IndicatorSet fields that map 1:1 to TechnicalIndicator columns.
_INDICATOR_COLUMNS = [
    "sma_20", "sma_50", "sma_200", "ema_12", "ema_26", "ema_50",
    "rsi_14", "macd", "macd_signal", "macd_hist", "adx_14", "atr_14",
    "supertrend", "supertrend_dir",
    "ichimoku_conversion", "ichimoku_base", "ichimoku_span_a", "ichimoku_span_b",
    "vwap", "obv", "mfi_14",
    "bb_upper", "bb_middle", "bb_lower", "keltner_upper", "keltner_lower",
    "donchian_upper", "donchian_lower",
    "relative_strength", "high_52w", "low_52w", "pct_from_52w_high",
    "trend_strength", "momentum", "volatility", "breakout_strength",
]


@dataclass(slots=True)
class TechnicalOutcome:
    security_id: int
    score: float | None
    coverage: float
    computed: bool


def _load_series(db: Session, security_id: int):
    rows = list(
        db.scalars(
            select(DailyPrice)
            .where(DailyPrice.security_id == security_id)
            .order_by(DailyPrice.date.asc())
        )
    )
    return rows


def _scoring_metrics(ind: IndicatorSet) -> dict[str, float | None]:
    c = ind.last_close
    m: dict[str, float | None] = {}
    if c is not None and ind.sma_50 is not None:
        m["above_sma50"] = 1.0 if c > ind.sma_50 else 0.0
    if c is not None and ind.sma_200 is not None:
        m["above_sma200"] = 1.0 if c > ind.sma_200 else 0.0
    if ind.sma_50 is not None and ind.sma_200 is not None:
        m["golden_cross"] = 1.0 if ind.sma_50 > ind.sma_200 else 0.0
    if ind.supertrend_dir is not None:
        m["supertrend"] = 1.0 if ind.supertrend_dir == 1 else 0.0
    if ind.macd_hist is not None and c:
        m["macd_hist_norm"] = ind.macd_hist / c
    m["rsi"] = ind.rsi_14
    m["momentum"] = ind.momentum
    m["adx"] = ind.adx_14
    m["pct_from_52w_high"] = ind.pct_from_52w_high
    if c is not None and ind.vwap is not None:
        m["above_vwap"] = 1.0 if c > ind.vwap else 0.0
    if ind.obv_rising is not None:
        m["obv_trend"] = 1.0 if ind.obv_rising else 0.0
    m["mfi"] = ind.mfi_14
    return {k: v for k, v in m.items() if v is not None}


def compute_for_security(db: Session, security: Security) -> TechnicalOutcome:
    rows = _load_series(db, security.id)
    if len(rows) < MIN_BARS:
        return TechnicalOutcome(security.id, None, 0.0, computed=False)

    close = np.array([float(r.close) for r in rows], dtype=float)
    high = np.array([float(r.high) if r.high is not None else float(r.close) for r in rows])
    low = np.array([float(r.low) if r.low is not None else float(r.close) for r in rows])
    volume = np.array([float(r.volume) if r.volume is not None else 0.0 for r in rows])

    ind = compute_indicators(high, low, close, volume)
    result = score_technical(_scoring_metrics(ind))
    as_of_bar = rows[-1].date

    _persist_indicators(db, security.id, as_of_bar, ind)
    _persist_score(db, security.id, result.score, result.breakdown)
    db.commit()

    return TechnicalOutcome(security.id, result.score, result.coverage, computed=True)


def compute_all(db: Session, limit: int | None = None) -> dict[str, int]:
    sec_ids = db.scalars(select(DailyPrice.security_id).distinct()).all()
    if limit is not None:
        sec_ids = sec_ids[:limit]
    scored = 0
    for sid in sec_ids:
        security = db.get(Security, sid)
        if security is None:
            continue
        outcome = compute_for_security(db, security)
        if outcome.computed and outcome.score is not None:
            scored += 1
    result = {"securities": len(sec_ids), "scored": scored}
    log.info("compute_all technical: %s", result)
    return result


# ── Persistence ───────────────────────────────────────────────
def _persist_indicators(
    db: Session, security_id: int, as_of: date, ind: IndicatorSet
) -> None:
    row = db.scalar(
        select(TechnicalIndicator).where(
            TechnicalIndicator.security_id == security_id,
            TechnicalIndicator.timeframe == Timeframe.D1,
            TechnicalIndicator.date == as_of,
        )
    )
    if row is None:
        row = TechnicalIndicator(
            security_id=security_id, timeframe=Timeframe.D1, date=as_of
        )
        db.add(row)
    for col in _INDICATOR_COLUMNS:
        setattr(row, col, getattr(ind, col))


def _persist_score(
    db: Session, security_id: int, score: float | None, breakdown: dict
) -> None:
    today = date.today()
    row = db.scalar(
        select(Score).where(Score.security_id == security_id, Score.as_of == today)
    )
    if row is None:
        row = Score(security_id=security_id, as_of=today)
        db.add(row)
    row.technical = score
    merged = dict(row.breakdown or {})
    merged["technical"] = breakdown
    row.breakdown = merged
