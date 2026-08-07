"""The quarter columns must be exactly the quarters the company actually has.

Reported as "sorting a quarter puts blanks at the top". It was not a sort fault - the sort
puts nulls last in both directions and always has. The grid was disagreeing with itself:

  * the CELL reads score_history / score_history_dates, which is rebuilt every run, and
    correctly showed nothing for a quarter the company has no point for;
  * the SORT reads the flat q_2026Q1 field, which was only ever ADDED and never removed, so a
    quarter that dropped out of a company's history kept its score indefinitely.

Sorting Mar-26 descending therefore put DPM at the top on a stale 97.01 while DPM's own cell in
that column was blank. 1,490 rows carried 1,605 such values.

The invariant that makes it impossible: the set of q_ keys equals the set of quarters in
score_history_dates. Enforced where the fields are written AND where they are carried between
snapshots, because both paths could reintroduce it.
"""

from __future__ import annotations

from app.ingestion.quality_history import (
    prune_quarter_columns as _prune_quarter_columns,
)
from app.ingestion.quality_history import (
    quarter_key as _quarter_key,
)


def test_a_quarter_no_longer_in_the_history_is_removed() -> None:
    """DPM, exactly as it shipped: two quarter fields, one history point."""
    row = {"symbol": "DPM", "score_history_dates": ["2026-06-30"],
           "q_2026Q1": 97.01, "q_2026Q2": 74.87, "price": 58.77}
    assert _prune_quarter_columns(row) == 1
    assert "q_2026Q1" not in row
    assert row["q_2026Q2"] == 74.87
    assert row["price"] == 58.77, "pruning touched a field it does not own"


def test_a_full_history_is_left_intact() -> None:
    row = {"score_history_dates": ["2025-12-31", "2026-03-31", "2026-06-30"],
           "q_2025Q4": 80.0, "q_2026Q1": 85.0, "q_2026Q2": 90.0}
    assert _prune_quarter_columns(row) == 0
    assert len([k for k in row if k.startswith("q_")]) == 3


def test_a_row_with_no_history_keeps_what_it_has() -> None:
    """A rebuild that produced nothing must not strip the row on the strength of a missing
    input - that would delete real data whenever a source was briefly unavailable."""
    row = {"q_2026Q1": 50.0}
    assert _prune_quarter_columns(row) == 0
    assert row["q_2026Q1"] == 50.0

    row = {"score_history_dates": [], "q_2026Q1": 50.0}
    assert _prune_quarter_columns(row) == 0


def test_every_quarter_key_matches_the_writer() -> None:
    """The pruner and the writer must spell a quarter the same way, or pruning deletes
    everything the writer just produced."""
    assert _quarter_key("2026-03-31") == "q_2026Q1"
    assert _quarter_key("2026-06-30") == "q_2026Q2"
    assert _quarter_key("2026-09-30") == "q_2026Q3"
    assert _quarter_key("2025-12-31") == "q_2025Q4"
    # Off-calendar fiscal ends land in the quarter their period end falls in.
    assert _quarter_key("2026-01-31") == "q_2026Q1"
    assert _quarter_key("2026-08-31") == "q_2026Q3"


def test_an_unreadable_date_does_not_delete_the_column_set() -> None:
    """A bad date must not resolve to a key that quietly prunes everything valid."""
    assert _quarter_key("") is None
    assert _quarter_key(None) is None
    assert _quarter_key("not-a-date") is None
    row = {"score_history_dates": ["2026-03-31", "garbage"], "q_2026Q1": 85.0}
    assert _prune_quarter_columns(row) == 0
    assert row["q_2026Q1"] == 85.0


def test_carrying_a_row_between_snapshots_cannot_reintroduce_a_phantom() -> None:
    """_carry_enrichment copies q_ fields by PREFIX, which is how a stale quarter survived an
    export even after the writer cleared it. The prune runs there too."""
    from app.cli import _carry_enrichment

    prior = {"q_2026Q1": 97.01, "q_2026Q2": 74.87, "quality_score": 74.87}
    fresh = {"symbol": "DPM", "score_history_dates": ["2026-06-30"], "quality_score": 74.87}
    out = _carry_enrichment(fresh, prior)
    assert "q_2026Q1" not in out, "the phantom came back through the carry"
    assert out["q_2026Q2"] == 74.87
