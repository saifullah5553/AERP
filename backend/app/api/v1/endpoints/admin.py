"""Admin endpoints to trigger ingestion jobs.

These only *enqueue* Celery tasks — the actual provider calls run in the worker,
never in the web process. (Auth is added in Phase 10; until then these are
intended for local/operator use.)
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/admin/ingest", tags=["admin"])


class EnqueuedTask(BaseModel):
    task_id: str
    task: str
    status: str = "queued"


def _enqueue(task, **kwargs) -> EnqueuedTask:
    try:
        async_result = task.delay(**kwargs)
    except Exception as exc:  # broker unreachable
        raise HTTPException(
            status_code=503, detail=f"Task broker unavailable: {exc.__class__.__name__}"
        ) from exc
    return EnqueuedTask(task_id=async_result.id, task=task.name)


@router.post("/quotes", response_model=EnqueuedTask, summary="Refresh quotes now")
def trigger_refresh_quotes(region: str | None = None, limit: int | None = None) -> EnqueuedTask:
    from app.tasks.ingestion import refresh_quotes_task

    return _enqueue(refresh_quotes_task, region=region, limit=limit)


@router.post("/daily", response_model=EnqueuedTask, summary="Backfill daily prices now")
def trigger_backfill_daily(
    region: str | None = None, start: str | None = None, limit: int | None = None
) -> EnqueuedTask:
    from app.tasks.ingestion import backfill_daily_task

    return _enqueue(backfill_daily_task, region=region, start=start, limit=limit)


@router.post("/universe", response_model=EnqueuedTask, summary="Discover universe now")
def trigger_load_universe(providers: list[str] | None = None) -> EnqueuedTask:
    from app.tasks.ingestion import load_universe_task

    return _enqueue(load_universe_task, providers=providers)


@router.post("/fundamentals", response_model=EnqueuedTask, summary="Ingest statements now")
def trigger_ingest_fundamentals(
    region: str | None = None, limit: int | None = None
) -> EnqueuedTask:
    from app.tasks.ingestion import ingest_fundamentals_task

    return _enqueue(ingest_fundamentals_task, region=region, limit=limit)


@router.post("/compute-fundamentals", response_model=EnqueuedTask, summary="Compute scores")
def trigger_compute_fundamentals(limit: int | None = None) -> EnqueuedTask:
    from app.tasks.ingestion import compute_fundamentals_task

    return _enqueue(compute_fundamentals_task, limit=limit)
