from __future__ import annotations

from app.ingestion.sector_taxonomy import (
    CANONICAL,
    canonical_sector,
    industry_for,
    normalize_rows,
)


def test_case_variants_collapse() -> None:
    # "Cement" and "CEMENT" were separate entries in the sector filter.
    assert canonical_sector("CEMENT") == canonical_sector("Cement") == "Basic Materials"
    assert canonical_sector("technology") == "Technology"


def test_gics_maps_onto_the_dominant_vocabulary() -> None:
    # Both spellings are correct; they just cannot coexist in one filter.
    assert canonical_sector("Consumer Discretionary") == "Consumer Cyclical"
    assert canonical_sector("Consumer Staples") == "Consumer Defensive"
    assert canonical_sector("Information Technology") == "Technology"
    assert canonical_sector("Health Care") == "Healthcare"
    assert canonical_sector("Financials") == "Financial Services"
    assert canonical_sector("Materials") == "Basic Materials"


def test_psx_exchange_categories_become_sectors() -> None:
    # These are industries reported in a sector field.
    assert canonical_sector("Modarabas") == "Financial Services"
    assert canonical_sector("Textile Spinning") == "Consumer Cyclical"
    assert canonical_sector("Sugar & Allied Industries") == "Consumer Defensive"
    assert canonical_sector("Oil & Gas Exploration Companies") == "Energy"


def test_exchange_detail_is_kept_as_industry_not_discarded() -> None:
    assert industry_for("TEXTILE SPINNING") == "Textile Spinning"
    assert industry_for("paper, board & packaging") == "Paper, Board & Packaging"
    # A real sector is not an industry.
    assert industry_for("Technology") is None


def test_meaningless_categories_stay_unmapped_for_a_human() -> None:
    # "Miscellaneous" names nothing. Filing it under a sector nobody chose would hide it.
    assert canonical_sector("Miscellaneous") is None
    assert canonical_sector("") is None
    assert canonical_sector(None) is None


def test_non_company_labels_survive() -> None:
    for label in ("Forex", "Crypto", "Index", "Commodity", "ETF"):
        assert canonical_sector(label) == label


def test_every_mapping_lands_inside_the_canonical_set() -> None:
    # A mapping that produces a value outside the set is a bug: it would reintroduce exactly
    # the fragmentation this module exists to remove.
    for value in ("Consumer Discretionary", "Modarabas", "CEMENT", "Health Care", "Refinery"):
        assert canonical_sector(value) in CANONICAL


def test_normalize_rows_rewrites_and_enriches() -> None:
    rows = [
        {"symbol": "A", "sector": "Consumer Staples"},
        {"symbol": "B", "sector": "TEXTILE SPINNING"},
        {"symbol": "C", "sector": "Technology"},
        {"symbol": "D", "sector": "Miscellaneous"},
        {"symbol": "E", "sector": "Cement", "industry": "Portland Cement"},
    ]
    stats = normalize_rows(rows)

    assert rows[0]["sector"] == "Consumer Defensive"
    assert rows[1]["sector"] == "Consumer Cyclical"
    assert rows[1]["industry"] == "Textile Spinning"
    assert rows[2]["sector"] == "Technology"          # already canonical, untouched
    assert rows[3]["sector"] is None                  # names nothing - cleared for a human
    assert rows[4]["industry"] == "Portland Cement"   # existing industry not overwritten
    assert stats["changed"] == 3
    assert stats["cleared"] == 1


def test_fund_categories_and_metals_are_mapped() -> None:
    # These arrived in a sector field from ETF and ASX feeds.
    assert canonical_sector("US Equity") == "ETF"
    assert canonical_sector("Thematic") == "ETF"
    assert canonical_sector("Precious Metals") == "Basic Materials"
    assert canonical_sector("Agriculture") == "Consumer Defensive"


def test_meaningless_values_are_cleared_not_kept() -> None:
    # "Miscellaneous" is not an answer. Clearing it puts the name in front of a human instead
    # of leaving it filed under a sector nobody chose.
    rows = [{"symbol": "A", "sector": "Miscellaneous"}, {"symbol": "B", "sector": "Class Pend"}]
    stats = normalize_rows(rows)
    assert rows[0]["sector"] is None
    assert rows[1]["sector"] is None
    assert stats["cleared"] == 2
