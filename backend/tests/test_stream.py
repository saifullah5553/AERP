from __future__ import annotations

import json

from app.api.v1.endpoints.stream import _passes_filter, quote_event_stream


def test_stream_opens_with_event() -> None:
    gen = quote_event_stream()
    first = next(gen)  # only take the immediate "open" frame; don't enter the loop
    gen.close()
    assert first.startswith("event: open")


def test_passes_filter_none_allows_all() -> None:
    assert _passes_filter(json.dumps({"symbol": "AAPL"}), None) is True


def test_passes_filter_matches() -> None:
    data = json.dumps({"symbol": "AAPL", "price": 1})
    assert _passes_filter(data, {"AAPL"}) is True
    assert _passes_filter(data, {"MSFT"}) is False


def test_passes_filter_bad_payload() -> None:
    assert _passes_filter("not-json", {"AAPL"}) is False
