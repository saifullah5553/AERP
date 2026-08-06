"""One spelling per sector, and an asset class on every row.

Both faults were reported as display bugs and neither was one.

The filter listed 71 sectors where there are 52, because 19 PSX sectors arrived as both
"Cement" and "CEMENT". Peer margins bucket on the raw string, so the shouting variant formed a
second group - one company, in some cases - that never reached MIN_PEER_GROUP. Those names were
graded against the absolute anchors rather than against their own industry, and nothing said so.

Selecting Equity returned 503 of 6,034 US names. Those 503 are the original S&P 500 universe,
the only rows ever given an asset_class; the field was never backfilled as the universe grew,
and the frontend compares it strictly, so 5,517 companies were simply absent from their own
asset class. Across all markets 9,961 of 11,109 rows had no class at all.
"""

from __future__ import annotations

import json

from app.ingestion.taxonomy import (
    asset_class_for,
    canonical_map,
    normalize_rows,
    normalize_snapshot,
)


def test_the_majority_spelling_wins() -> None:
    """Data-driven, not title-case-everything: the canonical form is what the sources already
    agree on, so no sector gets renamed to something nobody uses."""
    m = canonical_map(["Cement"] * 17 + ["CEMENT"])
    assert m["cement"] == "Cement"


def test_a_tie_prefers_the_variant_that_is_not_shouting() -> None:
    """LEASING COMPANIES and Leasing Companies both appeared twice. A coin-flip there would
    change the published sector between runs for no reason."""
    m = canonical_map(["LEASING COMPANIES", "LEASING COMPANIES",
                       "Leasing Companies", "Leasing Companies"])
    assert m["leasing companies"] == "Leasing Companies"


def test_the_map_is_stable_regardless_of_row_order() -> None:
    a = canonical_map(["CEMENT", "Cement", "Cement"])
    b = canonical_map(["Cement", "CEMENT", "Cement"])
    assert a == b


def test_every_row_gets_an_asset_class() -> None:
    """The bug in one line: a row with no class was invisible to every asset-class filter."""
    rows = [{"sector": "Cement"}, {"sector": None}, {"sector": "Technology"}]
    normalize_rows(rows)
    assert [r["asset_class"] for r in rows] == ["equity", "equity", "equity"]


def test_a_non_equity_is_classified_from_its_sector() -> None:
    """The convention the sector store already follows: a forex pair's sector IS 'Forex'."""
    rows = [{"sector": "Forex"}, {"sector": "Crypto"}, {"sector": "Index"},
            {"sector": "Commodity"}, {"sector": "ETF"}]
    normalize_rows(rows)
    assert [r["asset_class"] for r in rows] == ["forex", "crypto", "index", "commodity", "etf"]


def test_an_existing_class_is_not_overwritten_by_a_lookalike_sector() -> None:
    """A company in the 'Index' business is not an index. The loader's answer wins when it
    gave one."""
    assert asset_class_for("Index", "equity") == "equity"
    assert asset_class_for("Cement", "commodity") == "commodity"
    # ...but an unrecognised value is not preserved, or the field never gets repaired.
    assert asset_class_for("Cement", "junk") == "equity"


def test_case_variants_collapse_to_one_group() -> None:
    """The scoring consequence: these have to end up in ONE peer bucket, not two."""
    rows = [{"sector": "CEMENT"}, {"sector": "Cement"}, {"sector": "Cement"},
            {"sector": " Cement "}]
    normalize_rows(rows)
    assert {r["sector"] for r in rows} == {"Cement"}


def test_an_empty_sector_becomes_absent_rather_than_a_bucket() -> None:
    """An empty string groups every unlabelled row together and then reads as a real sector
    on the filter."""
    rows = [{"sector": ""}, {"sector": "   "}]
    normalize_rows(rows)
    assert all(r["sector"] is None for r in rows)


def test_the_screener_and_the_company_files_are_normalised_together(tmp_path) -> None:
    """They are two views of the same security and were disagreeing in both directions: the
    company files had an asset class for everything and the screener for almost nothing."""
    (tmp_path / "company").mkdir()
    (tmp_path / "screener.json").write_text(json.dumps([
        {"symbol": "LUCK", "sector": "CEMENT"},
        {"symbol": "DGKC", "sector": "Cement"},
        {"symbol": "MLCF", "sector": "Cement"},
    ]), encoding="utf-8")
    (tmp_path / "company" / "LUCK.json").write_text(
        json.dumps({"symbol": "LUCK", "sector": "CEMENT"}), encoding="utf-8")

    stats = normalize_snapshot(tmp_path)

    rows = json.loads((tmp_path / "screener.json").read_text(encoding="utf-8"))
    assert {r["sector"] for r in rows} == {"Cement"}
    assert all(r["asset_class"] == "equity" for r in rows)

    doc = json.loads((tmp_path / "company" / "LUCK.json").read_text(encoding="utf-8"))
    assert doc["sector"] == "Cement", "the company page still said CEMENT"
    assert doc["asset_class"] == "equity"
    assert stats["company_files"] == 1


def test_running_it_twice_changes_nothing_the_second_time(tmp_path) -> None:
    """It runs on every refresh. A normaliser that keeps rewriting is a normaliser that has
    not converged."""
    (tmp_path / "company").mkdir()
    (tmp_path / "screener.json").write_text(json.dumps([
        {"symbol": "A", "sector": "CEMENT"}, {"symbol": "B", "sector": "Cement"},
    ]), encoding="utf-8")
    normalize_snapshot(tmp_path)
    second = normalize_snapshot(tmp_path)
    assert second["renamed"] == 0
    assert second["classified"] == 0
    assert second["company_files"] == 0
