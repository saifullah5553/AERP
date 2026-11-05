"""The exchange's public pages, and the rule for trusting Yahoo's PSX history.

These exist because of a six-week silent freeze: the old endpoint began answering with an HTML
error page, the parser found no rows, nothing raised, and every PSX price and bar stopped on
24 Sep 2026 while the run stayed green.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.engines.price_action.relative import read
from app.ingestion.psx_bars import reconciles
from app.ingestion.psx_market import (
    PublicQuote,
    parse_as_of,
    parse_indices,
    parse_screener,
)

SCREENER = """
<table><thead><tr><th data-name="symbol">SYMBOL</th><th>SECTOR</th><th>LISTED IN</th>
<th>MARKET CAP.</th><th>PRICE</th><th>CHANGE (%)</th><th>1-YEAR CH. (%) *</th></tr></thead>
<tbody class="tbl__body">
<tr><td data-order="LUCK"><a class="tbl__symbol" href="/company/LUCK"><strong>LUCK</strong></a></td>
<td>0804</td><td>KSE100</td><td class="right" data-order="635000000000">635B</td>
<td class="right" data-order="433.5">433.50</td>
<td class="right" data-order="4.423"><i></i> 4.42%</td>
<td class="right" data-order="57.28">57.28%</td></tr>
<tr><td data-order="GIL"><a class="tbl__symbol" href="/company/GIL"><strong>GIL</strong></a>
<span class="badge">XD</span></td>
<td>0810</td><td>ALLSHR</td><td class="right" data-order="300000000">300M</td>
<td class="right" data-order="1000">1,000.00</td>
<td class="right" data-order="5.26">5.26%</td><td class="right" data-order="0.3">0.30%</td></tr>
<tr><td data-order="DEAD"><a class="tbl__symbol" href="/company/DEAD"><strong>DEAD</strong></a></td>
<td>0813</td><td>ALLSHR</td><td class="right" data-order="0">0</td>
<td class="right" data-order="0">0.00</td>
<td class="right" data-order="0">0.00%</td><td class="right" data-order="0">0%</td></tr>
</tbody></table>
"""

INDICES = """
<div>As of  Nov 5, 2026 2:30 PM</div>
<table><thead><tr><th>Index</th><th>High</th><th>Low</th><th>Current</th><th>Change</th></tr></thead>
<tbody><tr><td><a class="link" data-code="KSE100"><b>KSE100</b></a></td>
<td class="right" data-order="176604.51">176,604.51</td>
<td class="right" data-order="174291.25">174,291.25</td>
<td class="right" data-order="175261.46">175,261.46</td>
<td class="right" data-order="3247.98">3247.98</td>
<td class="right" data-order="1.888">1.89%</td></tr></tbody></table>
"""


def test_screener_reads_price_and_change_and_skips_unpriced_rows() -> None:
    rows = parse_screener(SCREENER)
    # GIL carries an XD badge beside its symbol; it must still file under GIL.
    assert [r.symbol for r in rows] == ["LUCK", "GIL"]
    assert rows[0].price == 433.5
    assert rows[0].change_pct == 4.423
    assert rows[0].market_cap == 635_000_000_000


def test_a_page_without_the_expected_headers_yields_nothing_rather_than_wrong_columns() -> None:
    assert parse_screener("<html><body>Page not found</body></html>") == []
    moved = SCREENER.replace("<th>PRICE</th>", "<th>LAST</th>")
    assert parse_screener(moved) == []


def test_implied_previous_close_is_what_yahoo_is_checked_against() -> None:
    quote = PublicQuote("LUCK", 433.5, 4.423, None)
    assert abs(quote.prev_close - 415.14) < 0.01


def test_indices_and_session_date() -> None:
    assert parse_indices(INDICES)["KSE100"]["current"] == 175261.46
    assert parse_as_of(INDICES) == date(2026, 11, 5)
    assert parse_as_of("<html>nothing here</html>") is None


def test_yahoo_history_is_accepted_only_when_it_reconciles() -> None:
    good = {"2026-11-03": (410.0, 100.0), "2026-11-04": (415.14, 200.0)}
    assert reconciles(good, 415.14, "2026-11-05")
    # GIL read 125.85 on Yahoo against 1,000 on the exchange.
    assert not reconciles({"2026-11-04": (125.85, 1.0)}, 1000.0, "2026-11-05")
    # The live session's partial bar is not evidence.
    assert not reconciles({"2026-11-05": (415.14, 1.0)}, 415.14, "2026-11-05")
    assert not reconciles(good, None, "2026-11-05")


def test_a_series_rebased_by_a_split_is_rejected_against_stored_history() -> None:
    history = {"2026-11-03": (83.0, 1.0), "2026-11-04": (83.03, 1.0)}
    assert reconciles(history, 83.03, "2026-11-05", {"2026-11-03": 83.0})
    assert not reconciles(history, 83.03, "2026-11-05", {"2026-11-03": 415.0})


def test_one_shifted_stored_day_does_not_reject_a_good_series() -> None:
    """Stored PSX closes from 30 Aug to 24 Sep 2026 sit one session late, so the newest shared
    day can differ by a day's move. Only a series that differs on most days is re-based."""
    history = {f"2026-09-{d:02d}": (100.0, 1.0) for d in range(1, 12)}
    stored = {f"2026-09-{d:02d}": 100.0 for d in range(1, 11)} | {"2026-09-11": 90.0}
    assert reconciles(history, 100.0, "2026-09-12", stored)


def _series(start: int, closes: list[float]) -> list[SimpleNamespace]:
    return [SimpleNamespace(date=f"day{start + i:04d}", close=c) for i, c in enumerate(closes)]


def test_relative_strength_matches_on_dates_across_a_hole_in_the_index() -> None:
    """A stock and an index that move identically must read as level, gap or no gap.

    Counting bars from the right would compare the stock's last 63 sessions with an index
    window stretching back past the hole, and report a lead that does not exist.
    """
    closes = [100 * 1.01**i for i in range(120)]
    stock = _series(0, closes)
    index = [b for i, b in enumerate(_series(0, closes)) if not 90 <= i < 100]
    result = read(stock, index)
    assert result.lead_pct is not None
    assert abs(result.lead_pct) < 0.01
