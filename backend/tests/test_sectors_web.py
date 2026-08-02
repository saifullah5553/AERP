from __future__ import annotations

from app.ingestion.sectors_web import sector_for_sic


def test_sector_for_sic_uses_specific_override_before_major_group() -> None:
    # 7372 (prepackaged software) must be Information Technology, not the 73 "services" default
    # it shares with staffing agencies - the override table exists for exactly this.
    assert sector_for_sic("7372") == "Information Technology"
    # 2800-series chemicals are Materials, even though major group 28 defaults to Health Care
    # (pharma dominates that group).
    assert sector_for_sic("2821") == "Materials"
    assert sector_for_sic("2834") == "Health Care"  # falls through to the 28 major group


def test_sector_for_sic_major_groups() -> None:
    assert sector_for_sic("3571") == "Information Technology"  # electronic computers
    assert sector_for_sic("3674") == "Information Technology"  # semiconductors
    assert sector_for_sic("6021") == "Financials"              # national commercial banks
    assert sector_for_sic("4911") == "Utilities"               # electric services
    assert sector_for_sic("1311") == "Energy"                  # crude petroleum
    assert sector_for_sic("6798") == "Real Estate"             # REITs


def test_sector_for_sic_pads_and_handles_missing() -> None:
    assert sector_for_sic(3571) == "Information Technology"  # non-str input
    assert sector_for_sic("100") == "Consumer Staples"  # padded to 0100 -> major group 01
    assert sector_for_sic(None) is None
    assert sector_for_sic("") is None
    assert sector_for_sic("9999") is None  # unmapped -> honest None, never a guess
