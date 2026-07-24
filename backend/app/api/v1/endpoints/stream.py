"""Server-Sent Events endpoint for live quotes.

Subscribes to the Redis ``quotes`` pub/sub channel (published by the ingestion
``refresh_quotes`` task) and streams updates to the browser as SSE. The generator
is synchronous; Starlette iterates it in a threadpool, so the Redis blocking read
never stalls the event loop. If Redis is unavailable the stream stays open and
emits heartbeats, so the client's EventSource simply receives no ticks rather than
erroring.
"""

from __future__ import annotations

import contextlib
import json
import time
from collections.abc import Iterator

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.core.cache import get_client
from app.core.logging import get_logger

router = APIRouter(prefix="/stream", tags=["stream"])
log = get_logger(__name__)

CHANNEL = "quotes"
HEARTBEAT_SECONDS = 15.0


def quote_event_stream(symbols: set[str] | None = None) -> Iterator[str]:
    # Announce the stream immediately so the client knows it's connected.
    yield "event: open\ndata: {}\n\n"

    client = get_client()
    if client is None:
        # No Redis: keep the connection alive with heartbeats.
        while True:
            time.sleep(1.0)
            yield ": ping\n\n"

    pubsub = client.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(CHANNEL)
    last_beat = time.monotonic()
    try:
        while True:
            message = pubsub.get_message(timeout=1.0)
            if message and message.get("type") == "message":
                data = message.get("data")
                if _passes_filter(data, symbols):
                    yield f"data: {data}\n\n"
            now = time.monotonic()
            if now - last_beat >= HEARTBEAT_SECONDS:
                last_beat = now
                yield ": ping\n\n"
    finally:  # client disconnected → Starlette closes the generator
        with contextlib.suppress(Exception):  # pragma: no cover
            pubsub.close()


def _passes_filter(data: object, symbols: set[str] | None) -> bool:
    if not symbols:
        return True
    try:
        return json.loads(data).get("symbol") in symbols  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


@router.get("/quotes", summary="Live quote stream (SSE)")
def stream_quotes(
    symbols: str | None = Query(None, description="Comma-separated provider symbols to filter"),
) -> StreamingResponse:
    symbol_set = {s.strip() for s in symbols.split(",")} if symbols else None
    return StreamingResponse(
        quote_event_stream(symbol_set),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable proxy buffering (nginx)
        },
    )
