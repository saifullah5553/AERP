"""The pass that sets the published score must score a company as what it is and where it is."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from app.engines.strategy import signal
from app.engines.strategy.quality import assess_quality
from app.ingestion import quality_history


def statements() -> dict[str, list[dict]]:
    """A profitable company, newest first, with twelve quarters of steady growth."""
    periods = [f"{2026 - i // 4}-{(3, 6, 9, 12)[3 - i % 4]:02d}-28" for i in range(12)]
    grow = [1.2 ** (-i / 4) for i in range(12)]
    return {
        "income": [{"fiscal_date": d, "period": "ttm", "revenue": 1000.0 * g,
                    "cost_of_revenue": 600.0 * g, "gross_profit": 400.0 * g,
                    "operating_income": 200.0 * g, "net_income": 150.0 * g, "ebitda": 260.0 * g,
                    "income_before_tax": 190.0 * g, "income_tax_expense": 40.0 * g,
                    "interest_expense": 10.0 * g, "eps": 1.5 * g, "weighted_shares": 100.0}
                   for d, g in zip(periods, grow, strict=True)],
        "balance": [{"fiscal_date": d, "total_assets": 2000.0 * g, "total_equity": 1000.0 * g,
                     "total_debt": 300.0, "cash_and_equivalents": 200.0 * g,
                     "current_assets": 700.0 * g, "current_liabilities": 400.0 * g}
                    for d, g in zip(periods, grow, strict=True)],
        "cashflow": [{"fiscal_date": d, "operating_cash_flow": 180.0 * g,
                      "capital_expenditure": -40.0 * g, "free_cash_flow": 140.0 * g,
                      "dividends_paid": -30.0 * g}
                     for d, g in zip(periods, grow, strict=True)],
    }


def test_the_country_changes_the_score() -> None:
    """If this stops holding, the tests below prove nothing about the published number."""
    market = {"price": 20.0, "market_cap": 2000.0}
    pakistan = assess_quality(statements(), market=market, region="psx")
    america = assess_quality(statements(), market=market, region="us")

    assert pakistan.score is not None and america.score is not None
    assert pakistan.score != america.score


def test_every_quarter_of_the_series_is_scored_for_its_country(monkeypatch) -> None:
    seen = []

    def spy(view, **kwargs):
        seen.append(kwargs)
        return assess_quality(view, **kwargs)

    monkeypatch.setattr(quality_history, "assess_quality", spy)

    series = quality_history._series_from_statements(
        {"statements_ttm": statements()}, "statements_ttm", lambda when: 20.0, None, "Financials",
        region="us", industry="Banks - Diversified")

    assert series and len(seen) >= 2
    assert {call["region"] for call in seen} == {"us"}
    assert {call["industry"] for call in seen} == {"Banks - Diversified"}


def test_the_published_score_is_the_country_score(tmp_path: Path, monkeypatch) -> None:
    """Through the real pass, from the screener row: this is where the region went missing."""
    (tmp_path / "company").mkdir()
    row = {"provider_symbol": "AAPL", "symbol": "AAPL", "region": "us", "sector": "Technology",
           "industry": "Consumer Electronics"}
    (tmp_path / "screener.json").write_text(json.dumps([row]), encoding="utf-8")
    (tmp_path / "company" / "AAPL.json").write_text(
        json.dumps({"statements_ttm": statements()}), encoding="utf-8")
    monkeypatch.setattr(quality_history, "_price_lookup", lambda region, symbol: lambda when: 20.0)
    monkeypatch.setattr(quality_history, "outdated", lambda series, doc: False)

    quality_history._refresh(tmp_path)

    saved = json.loads((tmp_path / "screener.json").read_text(encoding="utf-8"))[0]
    expected = assess_quality(statements(), market={"price": 20.0, "market_cap": 2000.0},
                              sector="Technology", region="us", industry="Consumer Electronics")
    assert saved["quality_score"] == expected.score


def test_the_strategy_gate_is_told_the_country_too(monkeypatch) -> None:
    seen = {}

    def stub(statements, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(eligible=False, reasons=["stub"], score=None, passed=False,
                               improving=False, checks={}, metrics={})

    monkeypatch.setattr(signal, "assess_quality", stub)
    bars = np.ones(5)

    signal.evaluate({}, bars, bars, bars, bars, sector="Financials", region="india",
                    industry="Banks - Regional")

    assert seen == {"sector": "Financials", "region": "india", "industry": "Banks - Regional"}
