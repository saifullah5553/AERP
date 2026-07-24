from __future__ import annotations

from datetime import date

import pytest
from app.core.config import settings
from app.ingestion.providers.binance import BinanceProvider
from app.ingestion.providers.fmp import FMPProvider
from app.ingestion.providers.psx import PSXProvider, parse_psx_html
from app.ingestion.providers.twelvedata import TwelveDataProvider
from app.models.enums import AssetClass, MarketRegion

from tests.mock_http import PSX_HTML, mock_client


# ── Binance (keyless) ─────────────────────────────────────────
def test_binance_quotes_symbol_mapping() -> None:
    p = BinanceProvider(mock_client())
    q = p.get_quotes(["BTC-USD", "ETH-USD"])
    assert set(q) == {"BTC-USD", "ETH-USD"}
    assert q["BTC-USD"].price == 65000.0
    assert q["BTC-USD"].prev_close == 64000.0
    assert q["BTC-USD"].volume == 12345


def test_binance_daily() -> None:
    p = BinanceProvider(mock_client())
    bars = p.get_daily("BTC-USD")
    assert len(bars) == 2
    assert bars[-1].close == 65000.0
    assert bars[0].date < bars[1].date  # ascending


def test_binance_universe_filters_non_usdt_and_inactive() -> None:
    p = BinanceProvider(mock_client())
    uni = p.list_universe()
    symbols = {s.symbol for s in uni}
    assert symbols == {"BTC", "ETH"}  # XRP (BTC-quoted) and OLD (break) excluded
    assert all(s.exchange == "CRYPTO" for s in uni)


def test_binance_supports() -> None:
    p = BinanceProvider()
    assert p.supports(AssetClass.CRYPTO, MarketRegion.GLOBAL)
    assert not p.supports(AssetClass.EQUITY, MarketRegion.US)


# ── PSX (keyless) ─────────────────────────────────────────────
def test_psx_parser() -> None:
    quotes = parse_psx_html(PSX_HTML)
    assert set(quotes) == {"LUCK.KA", "OGDC.KA"}
    luck = quotes["LUCK.KA"]
    assert luck.price == 445.63
    assert luck.change == 2.50
    assert luck.prev_close == pytest.approx(443.13)
    assert luck.volume == 1234567


def test_psx_provider_get_quotes_filters() -> None:
    p = PSXProvider(mock_client())
    q = p.get_quotes(["LUCK.KA"])
    assert set(q) == {"LUCK.KA"}  # OGDC present in HTML but not requested


# ── FMP (keyed) ───────────────────────────────────────────────
def test_fmp_unavailable_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "fmp_api_key", None)
    p = FMPProvider(mock_client())
    assert p.available is False
    assert p.get_quotes(["AAPL"]) == {}


def test_fmp_quotes_and_history(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "fmp_api_key", "test-key")
    p = FMPProvider(mock_client())
    q = p.get_quotes(["AAPL"])
    assert q["AAPL"].price == 200.0
    assert q["AAPL"].change_pct == 2.04

    bars = p.get_daily("AAPL", start=date(2026, 7, 1))
    assert len(bars) == 2
    assert bars[0].date < bars[1].date
    assert bars[-1].close == 200.0


def test_fmp_universe_filters_us_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "fmp_api_key", "test-key")
    p = FMPProvider(mock_client())
    uni = p.list_universe()
    symbols = {s.symbol for s in uni}
    # OTC excluded; BRK.B excluded (dot suffix); NASDAQ+NYSE kept.
    assert symbols == {"AAPL", "MSFT", "IBM"}


# ── Twelve Data (keyed) ───────────────────────────────────────
def test_twelvedata_forex_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "twelve_data_api_key", "test-key")
    p = TwelveDataProvider(mock_client())
    q = p.get_quotes(["EURUSD=X"])
    assert q["EURUSD=X"].price == 1.0850
    assert q["EURUSD=X"].prev_close == 1.0830


def test_twelvedata_daily(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "twelve_data_api_key", "test-key")
    p = TwelveDataProvider(mock_client())
    bars = p.get_daily("EURUSD=X")
    assert len(bars) == 2
    assert bars[0].date < bars[1].date
