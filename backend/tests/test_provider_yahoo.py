from __future__ import annotations

import pytest
from app.ingestion.providers.yahoo import YahooProvider
from app.models.enums import AssetClass, MarketRegion, StatementPeriod

from tests.fake_yahoo import FakeYahooFetcher


def provider() -> YahooProvider:
    return YahooProvider(fetcher=FakeYahooFetcher())


def test_universal_and_keyless() -> None:
    p = provider()
    assert p.available is True
    assert p.supports(AssetClass.EQUITY, MarketRegion.US)
    assert p.supports(AssetClass.FOREX, MarketRegion.GLOBAL)


def test_quotes_derives_change() -> None:
    q = provider().get_quotes(["AAPL", "EURUSD=X", "UNKNOWN"])
    assert set(q) == {"AAPL", "EURUSD=X"}  # unknown omitted, not fabricated
    assert q["AAPL"].price == 200.0
    assert q["AAPL"].prev_close == 196.0
    assert q["AAPL"].change == pytest.approx(4.0)
    assert q["AAPL"].change_pct == pytest.approx(4 / 196 * 100, rel=1e-4)


def test_daily_ascending() -> None:
    bars = provider().get_daily("AAPL")
    assert len(bars) == 2
    assert bars[0].date < bars[1].date
    assert bars[-1].close == 200.0


def test_statements_all_three() -> None:
    stmts = provider().get_statements("AAPL", StatementPeriod.ANNUAL)
    kinds = {s.statement_type for s in stmts}
    assert kinds == {"income", "balance", "cashflow"}
    income_latest = max(
        (s for s in stmts if s.statement_type == "income"), key=lambda s: s.fiscal_date
    )
    assert income_latest.values["revenue"] == 1200.0
    assert income_latest.values["net_income"] == 236.0


def test_quarterly_not_supported() -> None:
    assert provider().get_statements("AAPL", StatementPeriod.QUARTER) == []
