from __future__ import annotations

import json

import httpx
from app.ingestion.us_universe import SECClient, ingest_us_universe
from app.models.enums import MarketRegion
from app.models.market import Market, Security
from sqlalchemy import func, select
from sqlalchemy.orm import Session

_SEC_JSON = {
    "fields": ["cik", "name", "ticker", "exchange"],
    "data": [
        [1, "NVIDIA CORP", "NVDA", "Nasdaq"],
        [2, "APPLE INC", "AAPL", "Nasdaq"],
        [3, "EXXON MOBIL CORP", "XOM", "NYSE"],
        [4, "SOME OTC CO", "OTCX", "OTC"],        # skipped: OTC
        [5, "BERKSHIRE HATHAWAY B", "BRK.B", "NYSE"],  # skipped: dotted ticker
        [6, "CBOE THING", "CBOEX", "CBOE"],        # skipped: CBOE
    ],
}


def _mock_client() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.sec.gov":
            return httpx.Response(200, content=json.dumps(_SEC_JSON))
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _us_markets(db: Session) -> None:
    db.add_all([
        Market(code="NASDAQ", name="NASDAQ", region=MarketRegion.US, currency="USD",
               ticker_suffix=""),
        Market(code="NYSE", name="NYSE", region=MarketRegion.US, currency="USD",
               ticker_suffix=""),
    ])
    db.commit()


def test_sec_client_parses() -> None:
    entries = SECClient(_mock_client()).fetch()
    assert len(entries) == 6
    assert entries[0].ticker == "NVDA"
    assert entries[0].exchange == "Nasdaq"


def test_ingest_only_major_common_stocks(db: Session) -> None:
    _us_markets(db)
    result = ingest_us_universe(db, SECClient(_mock_client()))
    assert result["created"] == 3  # NVDA, AAPL, XOM only

    symbols = set(db.scalars(select(Security.symbol)).all())
    assert symbols == {"NVDA", "AAPL", "XOM"}
    # US suffix is empty → provider_symbol equals the ticker.
    nvda = db.scalar(select(Security).where(Security.symbol == "NVDA"))
    assert nvda.provider_symbol == "NVDA"
    assert nvda.name == "Nvidia Corp"  # title-cased from SEC's UPPERCASE
    assert nvda.cik == "0000000001"    # 10-digit zero-padded EDGAR id


def test_ingest_is_idempotent(db: Session) -> None:
    _us_markets(db)
    client = SECClient(_mock_client())
    ingest_us_universe(db, client)
    second = ingest_us_universe(db, client)
    assert second["created"] == 0
    assert db.scalar(select(func.count()).select_from(Security)) == 3


def test_limit(db: Session) -> None:
    _us_markets(db)
    result = ingest_us_universe(db, SECClient(_mock_client()), limit=2)
    assert result["created"] == 2
