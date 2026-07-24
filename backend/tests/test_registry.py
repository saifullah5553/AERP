from __future__ import annotations

from app.ingestion.registry import ProviderRegistry, SecurityRef
from app.models.enums import AssetClass, MarketRegion

from tests.fake_yahoo import FakeYahooFetcher
from tests.mock_http import mock_client

REFS = [
    SecurityRef("BTC-USD", AssetClass.CRYPTO, MarketRegion.GLOBAL),
    SecurityRef("LUCK.KA", AssetClass.EQUITY, MarketRegion.PSX),
    SecurityRef("AAPL", AssetClass.EQUITY, MarketRegion.US),
    SecurityRef("EURUSD=X", AssetClass.FOREX, MarketRegion.GLOBAL),
]


def _registry() -> ProviderRegistry:
    return ProviderRegistry(mock_client(), yahoo_fetcher=FakeYahooFetcher())


def test_routing_is_free_only() -> None:
    reg = _registry()
    assert reg.order_for(AssetClass.CRYPTO, MarketRegion.GLOBAL) == ["binance", "yahoo"]
    assert reg.order_for(AssetClass.EQUITY, MarketRegion.PSX) == ["psx", "yahoo"]
    assert reg.order_for(AssetClass.EQUITY, MarketRegion.US) == ["yahoo"]
    assert reg.order_for(AssetClass.FOREX, MarketRegion.GLOBAL) == ["yahoo"]
    # No paid providers are wired.
    for order in [
        reg.order_for(AssetClass.EQUITY, MarketRegion.INDIA),
        reg.order_for(AssetClass.COMMODITY, MarketRegion.GLOBAL),
    ]:
        assert "fmp" not in order and "twelvedata" not in order


def test_get_quotes_all_resolve_keyless() -> None:
    quotes = _registry().get_quotes(REFS)
    assert set(quotes) == {"BTC-USD", "LUCK.KA", "AAPL", "EURUSD=X"}
    assert quotes["BTC-USD"].price == 65000.0  # binance
    assert quotes["LUCK.KA"].price == 445.63    # psx portal
    assert quotes["AAPL"].price == 200.0        # yahoo
    assert quotes["EURUSD=X"].price == 1.0850   # yahoo


def test_psx_falls_back_to_yahoo() -> None:
    # XYZ.KA is not on the PSX portal fixture, so routing falls through to yahoo.
    ref = SecurityRef("XYZ.KA", AssetClass.EQUITY, MarketRegion.PSX)
    quotes = _registry().get_quotes([ref])
    assert quotes["XYZ.KA"].price == 55.0


def test_get_daily_uses_chain() -> None:
    bars = _registry().get_daily(SecurityRef("AAPL", AssetClass.EQUITY, MarketRegion.US))
    assert len(bars) == 2


def test_get_statements_via_yahoo() -> None:
    stmts = _registry().get_statements(
        SecurityRef("AAPL", AssetClass.EQUITY, MarketRegion.US)
    )
    assert {s.statement_type for s in stmts} == {"income", "balance", "cashflow"}
