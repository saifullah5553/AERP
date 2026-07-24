from __future__ import annotations

import pytest
from app.core.config import settings
from app.ingestion.registry import ProviderRegistry, SecurityRef
from app.models.enums import AssetClass, MarketRegion

from tests.mock_http import mock_client

REFS = [
    SecurityRef("BTC-USD", AssetClass.CRYPTO, MarketRegion.GLOBAL),
    SecurityRef("LUCK.KA", AssetClass.EQUITY, MarketRegion.PSX),
    SecurityRef("AAPL", AssetClass.EQUITY, MarketRegion.US),
    SecurityRef("EURUSD=X", AssetClass.FOREX, MarketRegion.GLOBAL),
]


def test_routing_order() -> None:
    reg = ProviderRegistry()
    assert reg.order_for(AssetClass.CRYPTO, MarketRegion.GLOBAL) == ["binance"]
    assert reg.order_for(AssetClass.EQUITY, MarketRegion.PSX) == ["psx"]
    assert reg.order_for(AssetClass.EQUITY, MarketRegion.US) == ["fmp", "twelvedata"]
    assert reg.order_for(AssetClass.FOREX, MarketRegion.GLOBAL) == ["twelvedata", "fmp"]


def test_get_quotes_all_resolve_with_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "fmp_api_key", "k")
    monkeypatch.setattr(settings, "twelve_data_api_key", "k")
    reg = ProviderRegistry(mock_client())
    quotes = reg.get_quotes(REFS)
    assert set(quotes) == {"BTC-USD", "LUCK.KA", "AAPL", "EURUSD=X"}
    assert quotes["BTC-USD"].price == 65000.0
    assert quotes["AAPL"].price == 200.0


def test_get_quotes_gated_by_availability(monkeypatch: pytest.MonkeyPatch) -> None:
    # No keys: only keyless providers (binance, psx) can resolve.
    monkeypatch.setattr(settings, "fmp_api_key", None)
    monkeypatch.setattr(settings, "twelve_data_api_key", None)
    reg = ProviderRegistry(mock_client())
    quotes = reg.get_quotes(REFS)
    assert set(quotes) == {"BTC-USD", "LUCK.KA"}


def test_get_daily_uses_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "fmp_api_key", "k")
    reg = ProviderRegistry(mock_client())
    bars = reg.get_daily(SecurityRef("AAPL", AssetClass.EQUITY, MarketRegion.US))
    assert len(bars) == 2
