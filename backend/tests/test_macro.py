from __future__ import annotations

from app.ingestion.macro import (
    WorldBankClient,
    currencies_in_use,
    ingest_macro,
)
from app.models.enums import AssetClass, MacroIndicatorType, MarketRegion
from app.models.macro import MacroIndicator
from app.models.market import Market, Security
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.mock_http import mock_client


def _seed_forex(db: Session) -> None:
    market = Market(code="FOREX", name="Forex", region=MarketRegion.GLOBAL,
                    currency="USD", ticker_suffix="=X")
    db.add(market)
    db.flush()
    db.add(Security(market_id=market.id, symbol="EURUSD", provider_symbol="EURUSD=X",
                    name="Euro/USD", asset_class=AssetClass.FOREX, currency="USD"))
    db.commit()


def test_worldbank_client_parses() -> None:
    pts = WorldBankClient(mock_client()).fetch("US", MacroIndicatorType.GDP_GROWTH, 2020, 2024)
    assert len(pts) == 2
    assert pts[0].value == 3.0
    assert pts[0].country == "US"


def test_currencies_in_use(db: Session) -> None:
    _seed_forex(db)
    assert currencies_in_use(db) == {"EUR", "USD"}


def test_ingest_macro_upserts_and_idempotent(db: Session) -> None:
    _seed_forex(db)
    client = WorldBankClient(mock_client())
    first = ingest_macro(db, client)
    assert first["countries"] == 2  # US + EMU
    assert first["points"] > 0
    count = db.scalar(select(func.count()).select_from(MacroIndicator))

    ingest_macro(db, client)  # second run must not duplicate
    assert db.scalar(select(func.count()).select_from(MacroIndicator)) == count
