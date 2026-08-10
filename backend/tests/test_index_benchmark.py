"""The benchmark comparison on the quarterly history.

The point of these is that "compounded +328%" means nothing on its own. Over the same stretch
the KSE-100 made 283%, so the rule's real edge was 44 points, not 328 - and the US rule, which
looked like a +88% win, actually LOST to the S&P by 63 points. The arithmetic below is what
turns one number into that answer, so it is worth pinning down.
"""

from __future__ import annotations

from app.ingestion.rebalance_ledger import INDEX_FOR_REGION, INDEX_NAMES, _index_move

SERIES = {
    "2026-03-02": 100.0,
    "2026-03-03": 110.0,   # a session the portfolio did not trade on
    "2026-06-01": 120.0,
}


def test_move_between_two_sessions() -> None:
    assert _index_move(SERIES, "2026-03-02", "2026-06-01") == 20.0


def test_a_holiday_takes_the_PREVIOUS_close() -> None:
    """An index does not print on a day it does not trade.

    On or BEFORE, deliberately: the level a portfolio was marked against on a market holiday is
    the last close before it, not the next one after it - which would read the future.
    """
    assert _index_move(SERIES, "2026-03-05", "2026-06-01") == round((120 / 110 - 1) * 100, 2)


def test_no_series_means_no_comparison() -> None:
    assert _index_move({}, "2026-03-02", "2026-06-01") is None


def test_missing_endpoints_mean_no_comparison() -> None:
    assert _index_move(SERIES, None, "2026-06-01") is None
    assert _index_move(SERIES, "2026-03-02", None) is None


def test_a_date_before_the_series_starts_is_not_guessed() -> None:
    """No close on or before the start: the honest answer is None, not the earliest level."""
    assert _index_move(SERIES, "2020-01-01", "2026-06-01") is None


def test_zero_length_period_is_none() -> None:
    assert _index_move(SERIES, "2026-06-01", "2026-06-01") is None
    assert _index_move(SERIES, "2026-06-01", "2026-03-02") is None


def test_every_market_has_a_named_benchmark() -> None:
    """Pakistan and Dubai were briefly mapped to None on the strength of one vendor's 404.

    Both indices exist and are published - ^DFMGI does not resolve but DFMGI.AE does, and the
    KSE-100 comes from the exchange itself. A market with no benchmark should be a deliberate
    decision, not a symbol that was guessed wrong.
    """
    for region in ("us", "india", "australia", "gcc", "psx", "dfm"):
        symbol = INDEX_FOR_REGION.get(region)
        assert symbol, f"{region} has no benchmark index"
        assert INDEX_NAMES.get(symbol), f"{symbol} has no display name"
