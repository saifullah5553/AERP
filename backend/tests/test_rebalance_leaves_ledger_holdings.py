"""The portfolio IS the ledger's open positions, so the quarterly pass must not edit them."""

from __future__ import annotations

import json
from pathlib import Path

from app.ingestion import model_portfolio


def test_a_ledger_portfolio_is_left_exactly_as_it_was(tmp_path: Path) -> None:
    """The US read a fiscal 2026-04-30 against the ledger's 2026-06-30 and swapped on every run."""
    doc = {"reconstructed": True, "basis_by_region": {"us": "2026-06-30"},
           "holdings": {"us": [{"provider_symbol": "NRIM", "symbol": "NRIM"}]}, "changes": []}
    path = tmp_path / model_portfolio.PORTFOLIO
    path.write_text(json.dumps(doc), encoding="utf-8")
    rows = [{"provider_symbol": "KGC", "symbol": "KGC", "region": "us", "price": 10.0,
             "quality_score": 99.0, "q_2026Q2": 99.0, "score_history_dates": ["2026-04-30"]}]
    (tmp_path / "screener.json").write_text(json.dumps(rows), encoding="utf-8")

    result = model_portfolio.rebalance(tmp_path)

    assert result == {"skipped": "ledger owns the holdings"}
    assert json.loads(path.read_text(encoding="utf-8")) == doc
