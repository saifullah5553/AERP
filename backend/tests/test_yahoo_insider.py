from __future__ import annotations

from app.ingestion.yahoo_insider import ingest_for_security, parse_rows
from app.models.corporate import InsiderTransaction
from app.models.enums import AssetClass, InsiderTransactionType, MarketRegion
from app.models.market import Market, Security
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def _row(shares, value, text, insider, pos, d):
    return {"Shares": shares, "Value": value, "Text": text, "Insider": insider,
            "Position": pos, "Transaction": "", "Start Date": d}


RAW = [
    _row("116", "34236.0", "Sale at price 295.14 per share", "BORDERS", "Officer", "2026-06-16"),
    _row("1000", "295140.0", "Purchase at price 295.14 per share", "DOE", "Director", "2026-06-10"),
    _row("65000", "0.0", "Stock Gift at price 0.00", "LEVINSON", "Director", "2026-05-27"),
    _row("5", "nan", "", "NOTYPE", "", "2026-05-01"),  # untyped → dropped
]


def test_parse_rows_classifies_and_prices() -> None:
    rows = parse_rows(RAW)
    kinds = [r.transaction_type for r in rows]
    assert InsiderTransactionType.SELL in kinds
    assert InsiderTransactionType.BUY in kinds
    assert InsiderTransactionType.GRANT in kinds
    assert len(rows) == 3  # the untyped row is dropped
    sell = next(r for r in rows if r.transaction_type == InsiderTransactionType.SELL)
    assert abs((sell.price or 0) - 295.14) < 1e-6


class _Fetcher:
    def transactions(self, provider_symbol: str):
        return RAW


def test_ingest_is_idempotent(db: Session) -> None:
    db.add(Market(code="NASDAQ", name="NASDAQ", region=MarketRegion.US, country="US",
                  currency="USD", ticker_suffix=""))
    db.add(Security(market_id=1, symbol="AAPL", provider_symbol="AAPL",
                    asset_class=AssetClass.EQUITY, currency="USD"))
    db.commit()
    sec = db.scalar(select(Security))
    n1 = ingest_for_security(db, _Fetcher(), sec)
    db.commit()
    n2 = ingest_for_security(db, _Fetcher(), sec)
    db.commit()
    assert n1 == 3 and n2 == 0
    assert db.scalar(select(func.count()).select_from(InsiderTransaction)) == 3
