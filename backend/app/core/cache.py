"""Redis cache helper.

A thin, fail-open wrapper: if Redis is unavailable the cache silently misses
rather than breaking ingestion. JSON is used for values so cached entries are
inspectable with ``redis-cli``.
"""

from __future__ import annotations

import contextlib
import json
import time
from typing import Any

import redis

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

_client: redis.Redis | None = None
# After a failed connect, don't retry for this many seconds — keeps ingestion fast
# when Redis is down instead of paying the connect timeout on every call.
_RETRY_BACKOFF_SECONDS = 30.0
_next_retry_at = 0.0


def get_client() -> redis.Redis | None:
    """Return a shared Redis client, or ``None`` if Redis can't be reached.

    Fails fast: once a connection attempt fails, subsequent calls short-circuit to
    ``None`` for a backoff window rather than re-paying the connect timeout.
    """
    global _client, _next_retry_at
    if _client is not None:
        return _client
    if time.monotonic() < _next_retry_at:
        return None
    try:
        client = redis.from_url(
            settings.redis_url,
            socket_connect_timeout=1,
            socket_timeout=1,
            decode_responses=True,
        )
        client.ping()
        _client = client
        return _client
    except Exception as exc:  # pragma: no cover - infra dependent
        _next_retry_at = time.monotonic() + _RETRY_BACKOFF_SECONDS
        log.warning("Redis unavailable, cache disabled for %ds: %s",
                    int(_RETRY_BACKOFF_SECONDS), exc.__class__.__name__)
        return None


def cache_get(key: str) -> Any | None:
    client = get_client()
    if client is None:
        return None
    try:
        raw = client.get(key)
        return json.loads(raw) if raw is not None else None
    except Exception:  # pragma: no cover
        return None


def cache_set(key: str, value: Any, ttl_seconds: int = 60) -> None:
    client = get_client()
    if client is None:
        return
    with contextlib.suppress(Exception):  # pragma: no cover
        client.set(key, json.dumps(value, default=str), ex=ttl_seconds)


def publish(channel: str, message: Any) -> None:
    """Publish a message for the live-price SSE/WS feed (Phase 9 consumes it)."""
    client = get_client()
    if client is None:
        return
    with contextlib.suppress(Exception):  # pragma: no cover
        client.publish(channel, json.dumps(message, default=str))
