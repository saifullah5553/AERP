"""The technical-only composite shrink.

What remains of this file. The yfinance backfill it used to cover is deleted: it scored
companies on Yahoo's quarterly AND annual statements, which is a second fundamental engine and
a banned data source, and it ran on a four-hourly scheduled task nobody had connected to the
CSV-only rule. Fundamentals now come from one place - our own quarterly-TTM CSVs, scored by
engines/strategy/fundamental_quality.py.
"""

from __future__ import annotations

from app.engines.composite.engine import WEIGHTS
from app.ingestion.expand_universe import _tech_only_composite


def test_tech_only_composite_shrinks_toward_neutral() -> None:
    # 50 + (tech - 50) * technical_weight — a raw technical can't masquerade as a full
    # composite. Asserted against the live weight so re-tuning WEIGHTS doesn't break this.
    w = WEIGHTS["technical"]
    assert _tech_only_composite(50.0) == 50.0
    assert _tech_only_composite(100.0) == round(50.0 + 50.0 * w, 2)
    assert _tech_only_composite(0.0) == round(50.0 - 50.0 * w, 2)
    # Shrunk toward neutral: a strong technical never reaches its raw value.
    assert 50.0 < _tech_only_composite(90.0) < 90.0
