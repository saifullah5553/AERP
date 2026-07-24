"""Liveness / readiness probe."""

from __future__ import annotations

import redis
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import __version__
from app.core.config import settings
from app.db.session import get_db
from app.schemas.common import HealthResponse

router = APIRouter(tags=["system"])


def _check_db(db: Session) -> str:
    try:
        db.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:  # pragma: no cover - depends on infra
        return f"error: {exc.__class__.__name__}"


def _check_redis() -> str:
    try:
        client = redis.from_url(settings.redis_url, socket_connect_timeout=2)
        client.ping()
        return "ok"
    except Exception as exc:  # pragma: no cover - depends on infra
        return f"error: {exc.__class__.__name__}"


@router.get("/health", response_model=HealthResponse, summary="Service health")
def health(db: Session = Depends(get_db)) -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=__version__,
        environment=settings.env,
        database=_check_db(db),
        redis=_check_redis(),
    )
