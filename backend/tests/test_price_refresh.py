from __future__ import annotations

from app.ingestion.price_refresh import _eps_ttm, _pe_ttm, parse_chart_meta


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


def _detail(income: list[dict]) -> dict:
    return {"statements": {"income": income}}


def test_eps_ttm_uses_latest_annual_when_no_quarterly() -> None:
    # PSX case: only annual filings → newest full-year EPS (itself a trailing year).
    d = _detail([
        {"period": "annual", "fiscal_date": "2026-03-31", "eps": 56.88},
        {"period": "annual", "fiscal_date": "2025-03-31", "eps": 49.11},
    ])
    assert _eps_ttm(d) == 56.88


def test_eps_ttm_sums_last_four_quarters_when_present() -> None:
    d = _detail([
        {"period": "quarterly", "fiscal_date": "2026-03-31", "eps": 3.0},
        {"period": "quarterly", "fiscal_date": "2025-12-31", "eps": 2.5},
        {"period": "quarterly", "fiscal_date": "2025-09-30", "eps": 2.0},
        {"period": "quarterly", "fiscal_date": "2025-06-30", "eps": 1.5},
        {"period": "quarterly", "fiscal_date": "2025-03-31", "eps": 9.0},  # ignored (5th)
        {"period": "annual", "fiscal_date": "2025-03-31", "eps": 99.0},    # ignored
    ])
    assert _eps_ttm(d) == 9.0  # 3.0+2.5+2.0+1.5, NOT the stray annual/5th-quarter


def test_eps_ttm_none_when_no_eps() -> None:
    assert _eps_ttm(_detail([{"period": "annual", "fiscal_date": "2026-03-31"}])) is None
    assert _eps_ttm({}) is None


def test_pe_ttm_basic_and_guards() -> None:
    assert _pe_ttm(440.91, 56.88) == 7.75
    assert _pe_ttm(100.0, 0) is None       # zero EPS → no meaningful P/E
    assert _pe_ttm(100.0, -5.0) is None    # loss-making → no P/E
    assert _pe_ttm(None, 5.0) is None
    assert _pe_ttm(100.0, None) is None
