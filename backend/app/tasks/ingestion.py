"""Celery ingestion tasks — thin wrappers over the pipeline functions.

Each task creates a real DB session and provider registry, runs a pipeline
function, and returns a JSON-serialisable summary for the Celery result backend.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.db.session import session_scope
from app.ingestion.pipeline import backfill_daily, load_universe, refresh_quotes
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
