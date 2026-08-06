"""An insurer's top line is called "Total Revenue", and it has to land in `revenue`.

stockanalysis labels the same line differently by industry. An industrial gets "Revenue"; an
insurer or a REIT gets "Total Revenue" - premiums plus investment income, or rental plus other,
summed to exactly the same thing. INCOME_MAP keys on the literal string, so without an alias
the metric does not go missing loudly, it goes missing silently.

Found 2026-08-06: 34 of 453 PSX companies and 5 US ones exported "Total Revenue" only. JSRR
could not be graded at all. Worse were the insurers - AICL, EFUG, IGIHL, JLICL and the rest -
which DID produce a score, computed against a revenue series that did not exist. A missing
number that still returns an answer is harder to catch than one that crashes.
"""

from __future__ import annotations

from app.ingestion.fundamentals_store import _lookup
from app.ingestion.psx_csv import INCOME_MAP


def test_total_revenue_resolves_to_the_revenue_row() -> None:
    """The alias, in the form the loader actually uses it."""
    metrics = {"Total Revenue": ["66.06", "65.71"], "Net Income": ["-60.38", "-31.1"]}
    assert _lookup(metrics, "Revenue") == ["66.06", "65.71"]


def test_a_plain_revenue_row_still_wins() -> None:
    """An exchange that reports both must not be re-pointed at the alias."""
    metrics = {"Revenue": ["100"], "Total Revenue": ["999"]}
    assert _lookup(metrics, "Revenue") == ["100"]


def test_absent_stays_absent() -> None:
    """A bank reporting neither must yield None, not an empty row that scores as zero."""
    assert _lookup({"Net Income": ["5"]}, "Revenue") is None


def test_revenue_is_a_key_the_map_actually_asks_for() -> None:
    """The alias is worthless if INCOME_MAP never looks up 'Revenue' in the first place."""
    assert "Revenue" in INCOME_MAP
    assert INCOME_MAP["Revenue"][0] == "revenue"


def test_the_alias_does_not_capture_revenue_as_reported() -> None:
    """JSRR's export also carries "Revenue as Reported" - a different, non-standardised line.

    Aliasing it would mix as-reported figures into a standardised series without any sign that
    two different bases had been averaged together.
    """
    metrics = {"Revenue as Reported": ["70.0"]}
    assert _lookup(metrics, "Revenue") is None
