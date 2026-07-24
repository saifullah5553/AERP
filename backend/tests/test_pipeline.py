from __future__ import annotations

import pytest
from app.core.config import settings
from app.ingestion.pipeline import backfill_daily, load_universe, refresh_quotes
from app.ingestion.registry import ProviderRegistry
from app.models.enums import AssetClass, MarketRegion
from app.models.market import Market, Security
from app.models.prices import DailyPrice
from app.models.quote import Quote
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.mock_http import mock_client


@pytest.fixture()
def universe_db(db: Session) -> Session:
    """Seed the four markets and one security each that the mocks can resolve."""
    markets = {
        "CRYPTO": Market(code="CRYPTO", name="Crypto", region=MarketRegion.GLOBAL,
                         currency="USD", ticker_suffix="-USD"),
        "FOREX": Market(code="FOREX", name="Forex", region=MarketRegion.GLOBAL,
                        currency="USD", ticker_suffix="=X"),
        "NASDAQ": Market(code="NASDAQ", name="NASDAQ", region=MarketRegion.US,
                         currency="USD", ticker_suffix=""),
        "PSX": Market(code="PSX", name="PSX", region=MarketRegion.PSX,
                      currency="PKR", ticker_suffix=".KA"),
    }
    db.add_all(markets.values())
    db.flush()

    db.add_all([
        Security(market_id=markets["CRYPTO"].id, symbol="BTC", provider_symbol="BTC-USD",
                 name="Bitcoin", asset_class=AssetClass.CRYPTO, currency="USD"),
        Security(market_id=markets["FOREX"].id, symbol="EURUSD", provider_symbol="EURUSD=X",
                 name="Euro/USD", asset_class=AssetClass.FOREX, currency="USD"),
        Security(market_id=markets["NASDAQ"].id, symbol="AAPL", provider_symbol="AAPL",
                 name="Apple", asset_class=AssetClass.EQUITY, currency="USD"),
        Security(market_id=markets["PSX"].id, symbol="LUCK", provider_symbol="LUCK.KA",
                 name="Lucky Cement", asset_class=AssetClass.EQUITY, currency="PKR"),
    ])
    db.commit()
    return db


def test_refresh_quotes_populates_snapshot(
    universe_db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "fmp_api_key", "k")
    monkeypatch.setattr(settings, "twelve_data_api_key", "k")
    result = refresh_quotes(universe_db, ProviderRegistry(mock_client()))
    assert result.requested == 4
    assert result.resolved == 4

    quotes = {q.security_id: q for q in universe_db.scalars(select(Quote))}
    assert len(quotes) == 4
    prices = {
        universe_db.get(Security, sid).provider_symbol: float(q.price)
        for sid, q in quotes.items()
    }
    assert prices["BTC-USD"] == 65000.0
    assert prices["AAPL"] == 200.0
    assert prices["EURUSD=X"] == 1.0850
    assert prices["LUCK.KA"] == 445.63


def test_refresh_quotes_is_idempotent(
    universe_db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "fmp_api_key", "k")
    monkeypatch.setattr(settings, "twelve_data_api_key", "k")
    reg = ProviderRegistry(mock_client())
    refresh_quotes(universe_db, reg)
    refresh_quotes(universe_db, reg)  # second run must not duplicate
    count = universe_db.scalar(select(func.count()).select_from(Quote))
    assert count == 4


def test_refresh_quotes_without_keys_only_keyless(
    universe_db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "fmp_api_key", None)
    monkeypatch.setattr(settings, "twelve_data_api_key", None)
    result = refresh_quotes(universe_db, ProviderRegistry(mock_client()))
    # Only crypto (binance) + PSX resolve; nothing fabricated for AAPL/EURUSD.
    assert result.resolved == 2


def test_backfill_daily_upserts_bars(universe_db: Session) -> None:
    reg = ProviderRegistry(mock_client())
    written = backfill_daily(universe_db, reg, region=MarketRegion.GLOBAL)
    btc = universe_db.scalar(select(Security).where(Security.provider_symbol == "BTC-USD"))
    bars = universe_db.scalar(
        select(func.count()).select_from(DailyPrice).where(DailyPrice.security_id == btc.id)
    )
    assert bars == 2
    assert written >= 2

    # Idempotent: re-running does not create duplicate dates.
    backfill_daily(universe_db, reg, region=MarketRegion.GLOBAL)
    bars_after = universe_db.scalar(
        select(func.count()).select_from(DailyPrice).where(DailyPrice.security_id == btc.id)
    )
    assert bars_after == 2


def test_load_universe_creates_new_securities(universe_db: Session) -> None:
    before = universe_db.scalar(select(func.count()).select_from(Security))
    result = load_universe(universe_db, ProviderRegistry(mock_client()), provider_names=["binance", "psx"])
    after = universe_db.scalar(select(func.count()).select_from(Security))

    # binance adds ETH (BTC exists); psx adds OGDC (LUCK exists).
    assert after == before + 2
    new_symbols = set(
        universe_db.scalars(select(Security.provider_symbol)).all()
    )
    assert {"ETH-USD", "OGDC.KA"} <= new_symbols
    assert result["created"] == 2


def test_load_universe_is_idempotent(universe_db: Session) -> None:
    reg = ProviderRegistry(mock_client())
    load_universe(universe_db, reg, provider_names=["binance", "psx"])
    second = load_universe(universe_db, reg, provider_names=["binance", "psx"])
    assert second["created"] == 0  # nothing new the second time
