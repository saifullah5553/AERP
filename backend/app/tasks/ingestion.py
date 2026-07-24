"""Celery ingestion tasks — thin wrappers over the pipeline functions.

Each task creates a real DB session and provider registry, runs a pipeline
function, and returns a JSON-serialisable summary for the Celery result backend.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.db.session import session_scope
from app.ingestion.pipeline import (
    backfill_daily,
    ingest_fundamentals,
    load_universe,
    refresh_quotes,
)
from app.ingestion.registry import ProviderRegistry
from app.models.enums import MarketRegion
from app.tasks.celery_app import celery_app

log = get_logger(__name__)


@celery_app.task(name="aerp.ingest.refresh_quotes")
def refresh_quotes_task(region: str | None = None, limit: int | None = None) -> dict:
    reg = MarketRegion(region) if region else None
    with session_scope() as db:
        result = refresh_quotes(db, ProviderRegistry(), region=reg, limit=limit)
    return {"requested": result.requested, "resolved": result.resolved}


@celery_app.task(name="aerp.ingest.backfill_daily")
def backfill_daily_task(
    region: str | None = None, start: str | None = None, limit: int | None = None
) -> dict:
    from datetime import date

    reg = MarketRegion(region) if region else None
    start_date = date.fromisoformat(start) if start else None
    with session_scope() as db:
        written = backfill_daily(db, ProviderRegistry(), region=reg, start=start_date, limit=limit)
    return {"bars_written": written}


@celery_app.task(name="aerp.ingest.load_universe")
def load_universe_task(providers: list[str] | None = None) -> dict:
    with session_scope() as db:
        return load_universe(db, ProviderRegistry(), provider_names=providers)


@celery_app.task(name="aerp.ingest.fundamentals")
def ingest_fundamentals_task(region: str | None = None, limit: int | None = None) -> dict:
    reg = MarketRegion(region) if region else None
    with session_scope() as db:
        return ingest_fundamentals(db, ProviderRegistry(), region=reg, limit=limit)


@celery_app.task(name="aerp.engine.compute_fundamentals")
def compute_fundamentals_task(limit: int | None = None) -> dict:
    """Compute ratios + fundamental scores from already-ingested statements."""
    from app.engines.fundamental.engine import compute_all

    with session_scope() as db:
        return compute_all(db, limit=limit)


@celery_app.task(name="aerp.engine.compute_technical")
def compute_technical_task(limit: int | None = None) -> dict:
    """Compute indicators + technical scores from already-ingested prices."""
    from app.engines.technical.engine import compute_all

    with session_scope() as db:
        return compute_all(db, limit=limit)


@celery_app.task(name="aerp.engine.detect_patterns")
def detect_patterns_task(limit: int | None = None) -> dict:
    """Detect chart/candlestick/harmonic patterns from already-ingested prices."""
    from app.engines.patterns.engine import compute_all

    with session_scope() as db:
        return compute_all(db, limit=limit)


@celery_app.task(name="aerp.engine.compute_composite")
def compute_composite_task(limit: int | None = None) -> dict:
    """Blend fundamental/technical/momentum/quality/risk into composite + signals."""
    from app.engines.composite.engine import compute_all

    with session_scope() as db:
        return compute_all(db, limit=limit)
