"""The source's twenty-quarter window must not become our ceiling.

stockanalysis publishes a rolling twenty quarters. Every time a company reports, the newest
quarter appears and the oldest drops off. Replacing our record with each scrape therefore loses
one quarter every three months - invisibly, because the file still holds a tidy twenty.
"""

from __future__ import annotations

from app.ingestion.fundamentals_store import merge_records


def _rec(periods: list[str], revenue: list[float]) -> dict:
    return {
        "periods": periods,
        "income": {"revenue": revenue},
        "balance": {"total_assets": [r * 2 for r in revenue]},
        "cashflow": {"operating_cash_flow": [r * 0.1 for r in revenue]},
    }


def test_a_new_quarter_arrives_without_the_oldest_being_lost() -> None:
    """The exact quarterly event: Jun-26 in, Sep-21 off the end of the source."""
    held = _rec(["2026-03-31", "2025-12-31", "2025-09-30"], [300.0, 200.0, 100.0])
    fresh = _rec(["2026-06-30", "2026-03-31", "2025-12-31"], [400.0, 300.0, 200.0])

    out = merge_records(held, fresh)
    assert out["periods"] == ["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30"]
    # The quarter the source dropped is still ours.
    assert out["income"]["revenue"][-1] == 100.0
    # And the new one landed at the front.
    assert out["income"]["revenue"][0] == 400.0


def test_history_grows_across_repeated_refreshes() -> None:
    """Four quarterly refreshes of a three-period window leave six periods, not three."""
    record = _rec(["2025-03-31", "2024-12-31", "2024-09-30"], [100.0, 90.0, 80.0])
    for i, (a, b, c) in enumerate([
        ("2025-06-30", "2025-03-31", "2024-12-31"),
        ("2025-09-30", "2025-06-30", "2025-03-31"),
        ("2025-12-31", "2025-09-30", "2025-06-30"),
    ], 1):
        record = merge_records(record, _rec([a, b, c], [110.0 + i, 105.0 + i, 100.0 + i]))
    assert len(record["periods"]) == 6
    assert record["periods"][0] == "2025-12-31"
    assert record["periods"][-1] == "2024-09-30"
    # Every column stays aligned to the period list, or the whole record is nonsense.
    for section in ("income", "balance", "cashflow"):
        for values in record[section].values():
            assert len(values) == len(record["periods"])


def test_a_restated_figure_wins() -> None:
    """Where the two overlap, the newer scrape is the better number."""
    held = _rec(["2026-03-31"], [300.0])
    fresh = _rec(["2026-03-31"], [317.5])
    out = merge_records(held, fresh)
    assert out["income"]["revenue"] == [317.5]


def test_a_metric_only_one_side_knows_about_survives() -> None:
    held = {"periods": ["2025-12-31"], "income": {"revenue": [100.0]},
            "balance": {}, "cashflow": {}}
    fresh = {"periods": ["2026-03-31"], "income": {"ebitda": [40.0]},
             "balance": {}, "cashflow": {}}
    out = merge_records(held, fresh)
    assert out["periods"] == ["2026-03-31", "2025-12-31"]
    assert out["income"]["revenue"] == [None, 100.0]
    assert out["income"]["ebitda"] == [40.0, None]


def test_merging_with_nothing_is_a_no_op() -> None:
    rec = _rec(["2026-03-31"], [1.0])
    assert merge_records(None, rec) == rec
    assert merge_records(rec, None) == rec
