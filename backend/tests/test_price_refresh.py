from __future__ import annotations

from app.ingestion.price_refresh import (
    _eps_ttm,
    _pe_ttm,
    parse_chart_meta,
    parse_chart_result,
    report_staleness,
)


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


# 2026-08-05, -06 and -07 at midnight UTC, so a zero gmtoffset keeps the dates as written.
_DAY = {"2026-08-05": 1785888000, "2026-08-06": 1785974400, "2026-08-07": 1786060800}


def _result(meta: dict, bars: list[tuple[str, float | None]]) -> dict:
    return {
        "meta": {"gmtoffset": 0, **meta},
        "timestamp": [_DAY[d] for d, _ in bars],
        "indicators": {"quote": [{"close": [c for _, c in bars]}]},
    }


def test_session_date_stamped_from_the_quote() -> None:
    q = parse_chart_result(_result(
        {"regularMarketPrice": 105.0, "regularMarketTime": _DAY["2026-08-07"]},
        [("2026-08-06", 100.0), ("2026-08-07", 105.0)]))
    assert q["as_of"] == "2026-08-07"


def test_a_frozen_quote_loses_to_newer_bars() -> None:
    """SABAR.NS served a July-2024 quote of 26.65 beside current bars showing 6.55."""
    q = parse_chart_result(_result(
        {"regularMarketPrice": 26.65, "regularMarketTime": _DAY["2026-08-05"] - 86400 * 700},
        [("2026-08-06", 6.80), ("2026-08-07", 6.55)]))
    assert q["price"] == 6.55
    assert q["as_of"] == "2026-08-07"
    assert q["from_bars"] is True
    assert round(q["change_pct"], 2) == -3.68


def test_a_quote_with_no_timestamp_loses_to_bars() -> None:
    """PMGOLD.AX returns regularMarketTime 0 - unjudgeable, so the bars decide."""
    q = parse_chart_result(_result(
        {"regularMarketPrice": 17.94, "regularMarketTime": 0},
        [("2026-08-06", 60.15), ("2026-08-07", 60.50)]))
    assert q["price"] == 60.50
    assert q["as_of"] == "2026-08-07"


def test_a_current_quote_beats_the_bars() -> None:
    """An intraday quote is fresher than today's partial bar - it must not be overwritten."""
    q = parse_chart_result(_result(
        {"regularMarketPrice": 313.33, "regularMarketTime": _DAY["2026-08-07"]},
        [("2026-08-06", 312.41), ("2026-08-07", 311.00)]))
    assert q["price"] == 313.33
    assert q.get("from_bars") is not True


def test_change_is_the_DAILY_move_not_the_window() -> None:
    """Over a 5-day range chartPreviousClose is the close before the window.

    Taking it turned Apple's 0.29% day into 1.43% and would have re-sorted every gainers and
    losers table in the app.
    """
    q = parse_chart_result(_result(
        {"regularMarketPrice": 313.33, "regularMarketTime": _DAY["2026-08-07"],
         "chartPreviousClose": 308.91},
        [("2026-08-05", 308.91), ("2026-08-06", 312.41), ("2026-08-07", 313.10)]))
    assert q["prev_close"] == 312.41, "prev close must be the previous SESSION"
    assert round(q["change_pct"], 2) == 0.29


def test_no_bars_leaves_the_quote_alone() -> None:
    q = parse_chart_result({"meta": {"regularMarketPrice": 50.0, "chartPreviousClose": 40.0}})
    assert q["price"] == 50.0 and q["change"] == 10.0


def test_a_priceless_response_is_none() -> None:
    assert parse_chart_result({"meta": {}}) is None


def test_stale_rows_are_counted_per_market() -> None:
    rows = [
        {"region": "us", "price_as_of": "2026-08-07"},
        {"region": "us", "price_as_of": "2026-07-31"},   # behind its market
        {"region": "us"},                                # never priced
        {"region": "psx", "price_as_of": "2026-08-07"},
        {"region": "global", "asset_class": "index"},    # no dated peer - not counted
    ]
    assert report_staleness(rows) == {"stale_rows": 1, "undated_rows": 1}


def test_weekend_crypto_does_not_make_every_index_stale() -> None:
    """Asset classes keep different calendars - crypto trades Saturday, the FTSE does not."""
    rows = [
        {"region": "global", "asset_class": "crypto", "price_as_of": "2026-08-08"},
        {"region": "global", "asset_class": "index", "price_as_of": "2026-08-07"},
        {"region": "global", "asset_class": "commodity", "price_as_of": "2026-08-07"},
    ]
    assert report_staleness(rows)["stale_rows"] == 0


def _detail(income: list[dict]) -> dict:
    return {"statements": {"income": income}}


def test_eps_ttm_reads_our_own_ttm_statements() -> None:
    """Not the annual `statements` block - that is where the deleted yfinance data lived."""
    d = {"statements_ttm": {"income": [
        {"fiscal_date": "2026-06-30", "eps": 56.88},
        {"fiscal_date": "2026-03-31", "eps": 49.11},
    ]},
        "statements": {"income": [{"period": "annual", "fiscal_date": "2025-12-31", "eps": 9.99}]}}
    assert _eps_ttm(d) == 56.88


def test_eps_ttm_skips_a_newest_period_with_no_eps() -> None:
    """The source publishes EPS a little after the rest of the statement.

    Giving up on the newest row would blank the P/E for a whole quarter every quarter.
    """
    d = {"statements_ttm": {"income": [
        {"fiscal_date": "2026-06-30"},                 # reported, EPS not yet filled
        {"fiscal_date": "2026-03-31", "eps": 170.21},
    ]}}
    assert _eps_ttm(d) == 170.21


def test_eps_ttm_ignores_the_annual_block_entirely() -> None:
    """No TTM EPS means no P/E, rather than quietly falling back to a banned source."""
    d = {"statements": {"income": [{"period": "annual", "fiscal_date": "2026-03-31",
                                    "eps": 56.88}]}}
    assert _eps_ttm(d) is None


def test_eps_ttm_none_when_no_eps() -> None:
    assert _eps_ttm(_detail([{"period": "annual", "fiscal_date": "2026-03-31"}])) is None
    assert _eps_ttm({}) is None


def test_pe_ttm_basic_and_guards() -> None:
    assert _pe_ttm(440.91, 56.88) == 7.75
    assert _pe_ttm(100.0, 0) is None       # zero EPS → no meaningful P/E
    assert _pe_ttm(100.0, -5.0) is None    # loss-making → no P/E
    assert _pe_ttm(None, 5.0) is None
    assert _pe_ttm(100.0, None) is None
