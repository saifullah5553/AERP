from __future__ import annotations

import json

import httpx
from app.ingestion.psx_insider_api import (
    PSXInsiderAPIClient,
    ingest_psx_insider_api,
    parse_items,
)
from app.models.corporate import InsiderTransaction
from app.models.enums import AssetClass, InsiderTransactionType, MarketRegion
from app.models.market import Market, Security
from sqlalchemy import func, select
from sqlalchemy.orm import Session

ITEMS = [
    {"symbol": "LUCK", "date": "2026-07-20", "person": "Ali Khan", "role": "Director",
     "nature": "BUY", "shares": 10000, "rate": 450, "value": 4500000},
    {"symbol": "LUCK", "date": "2026-07-18", "person": "Sara Ahmed", "role": "CEO",
     "nature": "SELL", "shares": 2000, "rate": 455, "value": 910000},
    {"symbol": "ZZZZ", "date": "2026-07-15", "person": "X", "role": "Director",
     "nature": "BUY", "shares": 5, "rate": 1, "value": 5},  # not in universe → unmatched
    {"symbol": "LUCK", "date": "bad", "person": "Y", "role": "D",
     "nature": "BUY", "shares": 1, "rate": 1, "value": 1},  # bad date → skipped
]


def test_parse_items() -> None:
    rows = parse_items(ITEMS)
    assert len(rows) == 3  # bad-date row dropped
    buy = next(r for r in rows if r.transaction_type == InsiderTransactionType.BUY)
    assert buy.symbol == "LUCK" and buy.shares == 10000 and buy.price == 450


def _handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text=json.dumps({"items": ITEMS}))


def test_ingest_matches_universe_and_is_idempotent(db: Session) -> None:
    db.add(Market(code="PSX", name="PSX", region=MarketRegion.PSX, country="PK",
                  currency="PKR", ticker_suffix=".KA"))
    db.add(Security(market_id=1, symbol="LUCK", provider_symbol="LUCK.KA",
                    asset_class=AssetClass.EQUITY, currency="PKR"))
    db.commit()
    client = PSXInsiderAPIClient(httpx.Client(transport=httpx.MockTransport(_handler)))

    r1 = ingest_psx_insider_api(db, client)
    assert r1["written"] == 2  # two LUCK rows
    assert r1["unmatched"] == 1  # ZZZZ not in universe
    r2 = ingest_psx_insider_api(db, client)
    assert r2["written"] == 0  # idempotent
    assert db.scalar(select(func.count()).select_from(InsiderTransaction)) == 2
