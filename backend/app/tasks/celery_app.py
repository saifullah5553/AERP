"""Celery application.

Ships the app, the trivial ``ping`` task, and (Phase 2) the ingestion tasks plus
their Beat schedule: quote refresh, daily-price backfill, and universe discovery.
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "aerp",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.jobs", "app.tasks.ingestion"],
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

# ── Beat schedule ─────────────────────────────────────────────
# Times are UTC. Quote cadence differs by market: crypto trades 24/7, equities
# are refreshed less aggressively to respect free-tier rate limits.
celery_app.conf.beat_schedule = {
    "refresh-crypto-quotes": {
        "task": "aerp.ingest.refresh_quotes",
        "schedule": 60.0,  # every minute
        "kwargs": {"region": "global"},
    },
    "refresh-all-quotes": {
        "task": "aerp.ingest.refresh_quotes",
        "schedule": 300.0,  # every 5 minutes
    },
    "backfill-daily-prices": {
        "task": "aerp.ingest.backfill_daily",
        "schedule": crontab(hour=22, minute=30),  # after US close
    },
    "load-universe": {
        "task": "aerp.ingest.load_universe",
        "schedule": crontab(hour=1, minute=0),  # nightly discovery (crypto/psx)
    },
    "load-us-universe": {
        "task": "aerp.ingest.us_universe",
        "schedule": crontab(day_of_week=0, hour=1, minute=30),  # weekly SEC refresh
    },
    "ingest-fundamentals": {
        "task": "aerp.ingest.fundamentals",
        "schedule": crontab(hour=3, minute=0),  # nightly statement refresh
    },
    "ingest-psx-csv": {
        "task": "aerp.ingest.psx_csv",
        "schedule": crontab(hour=3, minute=20),  # re-scan the PSX CSV folder
    },
    "compute-fundamentals": {
        "task": "aerp.engine.compute_fundamentals",
        "schedule": crontab(hour=4, minute=0),  # recompute scores after ingest
    },
    "compute-technical": {
        "task": "aerp.engine.compute_technical",
        "schedule": crontab(hour=23, minute=0),  # after daily-price backfill
    },
    "detect-patterns": {
        "task": "aerp.engine.detect_patterns",
        "schedule": crontab(hour=23, minute=20),  # after technical compute
    },
    "ingest-macro": {
        "task": "aerp.ingest.macro",
        "schedule": crontab(hour=2, minute=30),  # weekly-ish cadence is fine; keep daily
    },
    "compute-forex-fundamentals": {
        "task": "aerp.engine.compute_forex_fundamentals",
        "schedule": crontab(hour=4, minute=30),  # after macro ingest
    },
    "ingest-insider": {
        "task": "aerp.ingest.insider",
        "schedule": crontab(hour=2, minute=0),  # SEC Form 4 for US securities
    },
    "ingest-psx-insider": {
        "task": "aerp.ingest.psx_insider",
        "schedule": crontab(hour=2, minute=15),  # re-load the PSX insider CSV
    },
    "ingest-news": {
        "task": "aerp.ingest.news",
        "schedule": crontab(hour="*/6"),  # refresh news every 6 hours
    },
    "compute-insider": {
        "task": "aerp.engine.compute_insider",
        "schedule": crontab(hour=4, minute=45),  # after insider ingest
    },
    "compute-composite": {
        "task": "aerp.engine.compute_composite",
        "schedule": crontab(hour=5, minute=0),  # after all fundamentals + technical land
    },
}
