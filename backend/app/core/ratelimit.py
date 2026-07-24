"""Redis-backed fixed-window rate limiting.

A lightweight per-client-IP limiter. It **fails open**: if Redis is unavailable,
requests are allowed rather than blocked, so a cache outage never takes the API
down. Streaming, health, and docs routes are exempt.
"""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.cache import get_client
from app.core.config import settings

WINDOW_SECONDS = 60


def check_rate_limit(client, key: str, limit: int, window: int = WINDOW_SECONDS):
    """Increment the window counter and decide if the request is allowed.

    Returns ``(allowed, remaining, retry_after)``.
    """
    count = int(client.incr(key))
    if count == 1:
        client.expire(key, window)
    ttl = int(client.ttl(key))
    if ttl < 0:
        ttl = window
    allowed = count <= limit
    remaining = max(0, limit - count)
    retry_after = ttl if not allowed else 0
    return allowed, remaining, retry_after


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limit: int | None = None) -> None:
        super().__init__(app)
        self.limit = limit or settings.rate_limit_per_minute
        prefix = settings.api_v1_prefix
        self.exempt = (
            f"{prefix}/stream",
            f"{prefix}/health",
            "/docs",
            "/redoc",
            "/openapi.json",
        )

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if path == "/" or path.startswith(self.exempt):
            return await call_next(request)

        client = get_client()
        if client is None:  # fail open when Redis is down
            return await call_next(request)

        ip = request.client.host if request.client else "unknown"
        bucket = int(time.time() // WINDOW_SECONDS)
        key = f"rl:{ip}:{bucket}"
        try:
            allowed, remaining, retry_after = check_rate_limit(client, key, self.limit)
        except Exception:  # any Redis hiccup → fail open
            return await call_next(request)

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Slow down."},
                headers={"Retry-After": str(retry_after)},
            )
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
