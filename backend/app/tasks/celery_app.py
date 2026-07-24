"""Celery application.

Phase 1 ships the app plus a trivial ``ping`` task so the worker and Beat
containers are wired and observable. Phase 2 adds ingestion tasks and the Beat
schedule (universe refresh, daily prices, score recompute).
"""

from __future__ import annotations

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "aerp",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.jobs"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=60 * 30,       # hard 30-min ceiling per task
    task_soft_time_limit=60 * 25,
    worker_max_tasks_per_child=200,  # recycle workers to bound memory
    broker_connection_retry_on_startup=True,
)

# Beat schedule is populated in Phase 2.
celery_app.conf.beat_schedule = {}
