"""A rebalance ranks the whole market on ONE quarter, once most of it has reported.

Ranking is a comparison. Using each company's own latest figures would judge a business on
June against one judged on March, and reward whoever filed first rather than whoever is better.
On 5 August 2026 only 11% of PSX had filed Jun-26.
"""

from __future__ import annotations

from app.ingestion.model_portfolio import _quarter_key, basis_quarter


def _market(reported: dict[str, int], region: str = "psx") -> list[dict]:
    """Rows for a market, from {period end: how many companies have filed it}."""
    rows = []
    n = 0
    for period, count in reported.items():
        for _ in range(count):
            n += 1
            rows.append({
                "region": region, "symbol": f"S{n}", "provider_symbol": f"S{n}",
                "quality_score": 50.0, "results_through": period, "price": 10.0,
            })
    return rows


def test_a_thinly_reported_quarter_is_not_the_basis() -> None:
    """49 of 432 is the real PSX position on 5 August. It must not trigger a rebalance."""
    rows = _market({"2026-06-30": 49, "2026-03-31": 383})
    assert basis_quarter(rows, "psx", "2026-08-05") == "2026-03-31"


def test_it_becomes_the_basis_once_most_of_the_market_has_filed() -> None:
    rows = _market({"2026-06-30": 350, "2026-03-31": 82})
    assert basis_quarter(rows, "psx", "2026-09-01") == "2026-06-30"


def test_coverage_is_not_enough_the_trade_date_must_also_have_arrived() -> None:
    """Jun-26 results are acted on at the end of August, not the day coverage crosses.

    Even with the whole market reported, nobody could have traded on 1 July what was published
    through June - the two-month lag is the same one the ledger uses.
    """
    rows = _market({"2026-06-30": 400})
    assert basis_quarter(rows, "psx", "2026-07-01") is None
    assert basis_quarter(rows, "psx", "2026-08-29") == "2026-06-30"


def test_it_falls_back_to_the_newest_quarter_that_is_well_covered() -> None:
    """Sep-26 has only 45% - not enough. Jun-26 has 91% once Sep filers are counted in, since
    a company reporting September has plainly reported June."""
    rows = _market({"2026-09-30": 200, "2026-06-30": 200, "2026-03-31": 40})
    assert basis_quarter(rows, "psx", "2026-12-01") == "2026-06-30"


def test_a_market_with_nothing_scored_has_no_basis() -> None:
    assert basis_quarter([], "psx", "2026-08-05") is None


def test_the_quarter_key_matches_the_screener_column() -> None:
    """The basis is looked up as a q_ field, so it has to spell them the same way."""
    assert _quarter_key("2026-03-31") == "q_2026Q1"
    assert _quarter_key("2026-06-30") == "q_2026Q2"
    assert _quarter_key("2025-12-31") == "q_2025Q4"
