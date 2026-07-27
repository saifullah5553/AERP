from __future__ import annotations

from app.ingestion.price_refresh import parse_chart_meta


def test_parse_chart_meta_computes_change() -> None:
    meta = {
        "regularMarketPrice": 105.0,
        "chartPreviousClose": 100.0,
        "regularMarketOpen": 101.0,
        "regularMarketDayHigh": 106.0,
        "regularMarketDayLow": 100.5,
        "regularMarketVolume": 12345,
    }
    q = parse_chart_meta(meta)
    assert q is not None
    assert q["price"] == 105.0
    assert q["prev_close"] == 100.0
    assert q["change"] == 5.0
    assert round(q["change_pct"], 2) == 5.0
    assert q["volume"] == 12345


def test_parse_chart_meta_falls_back_to_previousClose() -> None:
    q = parse_chart_meta({"regularMarketPrice": 50.0, "previousClose": 40.0})
    assert q["prev_close"] == 40.0
    assert q["change"] == 10.0


def test_parse_chart_meta_no_price_returns_none() -> None:
    assert parse_chart_meta({"previousClose": 40.0}) is None


def test_parse_chart_meta_zero_prev_no_change() -> None:
    q = parse_chart_meta({"regularMarketPrice": 50.0, "chartPreviousClose": 0})
    assert q["change"] is None and q["change_pct"] is None
