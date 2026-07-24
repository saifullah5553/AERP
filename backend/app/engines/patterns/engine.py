"""Pattern-engine orchestration.

Runs the candlestick, chart, and harmonic detectors over a security's stored daily
OHLC, then refreshes ``pattern_detections``: previously-active rows are deactivated
and the current findings inserted as active (history is retained, not deleted).

Elliott-wave and Wyckoff-phase labelling are deliberately **not** implemented:
rigorous automated detection of those is unreliable, and emitting guesses would
violate the platform's no-fabrication rule. They can be added later behind an
explicitly-labelled confidence model.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.engines.patterns.base import PatternHit
from app.engines.patterns.candlestick import detect_candlesticks
from app.engines.patterns.chart import detect_chart_patterns
from app.engines.patterns.harmonic import detect_harmonic_patterns
from app.models.enums import Timeframe
from app.models.market import Security
from app.models.prices import DailyPrice
from app.models.technical import PatternDetection

log = get_logger(__name__)

MIN_BARS = 30


@dataclass(slots=True)
class PatternOutcome:
    security_id: int
    detected: int
    top_pattern: str | None
    computed: bool


def detect_all(
    o: np.ndarray, h: np.ndarray, low: np.ndarray, c: np.ndarray
) -> list[PatternHit]:
    hits: list[PatternHit] = []
    hits += detect_candlesticks(o, h, low, c)
    hits += detect_chart_patterns(h, low, c)
    hits += detect_harmonic_patterns(h, low, c)
    return hits


def compute_for_security(db: Session, security: Security) -> PatternOutcome:
    return _run(db, security, _load_prices(db, security.id))


def _run(db: Session, security: Security, rows: list) -> PatternOutcome:
    if len(rows) < MIN_BARS:
        return PatternOutcome(security.id, 0, None, computed=False)

    o = np.array([float(r.open) if r.open is not None else float(r.close) for r in rows])
    h = np.array([float(r.high) if r.high is not None else float(r.close) for r in rows])
    low = np.array([float(r.low) if r.low is not None else float(r.close) for r in rows])
    c = np.array([float(r.close) for r in rows], dtype=float)

    hits = detect_all(o, h, low, c)
    detected_on = rows[-1].date

    # Deactivate the prior snapshot, then insert the fresh findings.
    db.execute(
        update(PatternDetection)
        .where(
            PatternDetection.security_id == security.id,
            PatternDetection.is_active.is_(True),
        )
        .values(is_active=False)
    )

    top: PatternHit | None = None
    for hit in hits:
        start_date = None
        if hit.start_index is not None and 0 <= hit.start_index < len(rows):
            start_date = rows[hit.start_index].date
        db.add(
            PatternDetection(
                security_id=security.id,
                timeframe=Timeframe.D1,
                detected_on=detected_on,
                name=hit.name,
                category=hit.category,
                direction=hit.direction,
                confidence=round(hit.confidence, 4),
                is_active=True,
                start_date=start_date,
                breakout_level=hit.breakout_level,
                target_price=hit.target_price,
                stop_level=hit.stop_level,
            )
        )
        if top is None or hit.confidence > top.confidence:
            top = hit
    db.commit()

    return PatternOutcome(security.id, len(hits), top.name if top else None, computed=True)


def compute_all(db: Session, limit: int | None = None) -> dict[str, int]:
    sec_ids = db.scalars(select(DailyPrice.security_id).distinct()).all()
    if limit is not None:
        sec_ids = sec_ids[:limit]
    total = 0
    for sid in sec_ids:
        security = db.get(Security, sid)
        if security is None:
            continue
        rows = _load_prices(db, sid)
        outcome = _run(db, security, rows)
        total += outcome.detected
    result = {"securities": len(sec_ids), "patterns": total}
    log.info("compute_all patterns: %s", result)
    return result


def _load_prices(db: Session, security_id: int) -> list:
    return list(
        db.scalars(
            select(DailyPrice)
            .where(DailyPrice.security_id == security_id)
            .order_by(DailyPrice.date.asc())
        )
    )
