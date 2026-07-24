"""Celery task definitions.

Phase 1: a health/ping task and a manual seed task. Ingestion and analytics tasks
are added in later phases.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.tasks.celery_app import celery_app

log = get_logger(__name__)


@celery_app.task(name="aerp.ping")
def ping() -> str:
    """Liveness check for the worker."""
    log.info("ping")
    return "pong"


@celery_app.task(name="aerp.seed_reference_data")
def seed_reference_data() -> dict[str, int]:
    """Run the idempotent reference-data seed from a worker."""
    from app.db.seed import seed_all

    return seed_all()
