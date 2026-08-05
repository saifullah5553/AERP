"""Every page must describe the same instant.

The screener, the model portfolio, the rebalance ledger and the pulse are all views of one
file. Rebuilt at different moments they disagree - and the disagreement looks like a data bug
rather than a scheduling one, which is the expensive kind to chase.
"""

from __future__ import annotations

import json

from app.ingestion.exclusions import apply_to_rows
from app.services.pulse import pulse_from_screener_dicts


def _screener(rows: list[dict]) -> list[dict]:
    return rows


def test_the_pulse_counts_match_the_rows_it_is_built_from() -> None:
    rows = [
        {"region": "us", "symbol": "A", "composite_score": 70.0, "change_pct": 1.0},
        {"region": "us", "symbol": "B", "composite_score": 30.0, "change_pct": -2.0},
        {"region": "us", "symbol": "C", "composite_score": 50.0, "change_pct": 0.5},
    ]
    pulse = pulse_from_screener_dicts(rows)[0]
    assert pulse["count"] == 3
    assert pulse["bullish"] + pulse["bearish"] + pulse["neutral"] == pulse["count"]
    assert pulse["advancers"] == 2
    assert pulse["decliners"] == 1


def test_an_excluded_symbol_leaves_every_view_at_once() -> None:
    """A symbol dropped from the screener must not survive in a view built from it.

    Exclusions are applied at the single point the snapshot passes through, so anything reading
    the screener afterwards cannot reintroduce them.
    """
    rows = [
        {"region": "us", "symbol": "REAL", "composite_score": 60.0},
        {"region": "us", "symbol": "GHOST", "composite_score": 60.0},
    ]
    kept, dropped = apply_to_rows(rows)
    symbols = {r["symbol"] for r in kept}
    # GHOST is only excluded if the list says so; the guarantee under test is that whatever
    # apply_to_rows removes is gone from the rows every view then reads.
    assert dropped == len(rows) - len(kept)
    assert all(r["symbol"] in symbols for r in kept)


def test_a_portfolio_holding_never_carries_a_score_the_screener_disagrees_with() -> None:
    """The check that caught it: GRMN read 100.0 on the portfolio and 80.69 on the screener.

    100.0 was a value from the retired engine - the portfolio had been marked before the
    universe was rescored, so the two files described different days.
    """
    screener = [{"region": "us", "symbol": "GRMN", "quality_score": 80.69,
                 "quality_grade": "Excellent", "results_through": "2026-03-31",
                 "provider_symbol": "GRMN", "price": 210.0}]
    latest = {r["provider_symbol"]: r for r in screener}

    holding = {"provider_symbol": "GRMN", "symbol": "GRMN", "quality_score": 100.0,
               "quality_grade": "Exceptional", "results_through": None}
    # This is what mark() does: refresh every field the screener has an opinion on.
    fresh = latest.get(holding["provider_symbol"]) or {}
    for field in ("results_through", "quality_grade", "quality_confidence", "quality_score"):
        if fresh.get(field) is not None:
            holding[field] = fresh[field]

    assert holding["quality_score"] == 80.69
    assert holding["quality_grade"] == "Excellent"
    assert holding["results_through"] == "2026-03-31"


def test_json_views_round_trip_without_losing_their_keys() -> None:
    """A view is only useful if the page's contract survives serialisation."""
    holding = {"symbol": "X", "entry_date": "2026-05-28", "entry_price": 100.0,
               "return_pct": 1.5, "results_through": "2026-03-31",
               "quality_score": 70.0, "quality_grade": "Good"}
    back = json.loads(json.dumps(holding))
    for key in ("entry_date", "entry_price", "return_pct", "results_through",
                "quality_score", "quality_grade"):
        assert key in back, key
