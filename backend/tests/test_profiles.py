from __future__ import annotations

from app.ingestion.profiles import ingest_profiles
from app.models.enums import AssetClass, MarketRegion
from app.models.market import Market, Security
from sqlalchemy import select
from sqlalchemy.orm import Session


class _Fetcher:
    def __init__(self, text: str | None = "Acme makes anvils and rockets.") -> None:
        self.text = text
        self.calls: list[str] = []

    def summary(self, provider_symbol: str) -> str | None:
        self.calls.append(provider_symbol)
        return self.text


def _seed(db: Session) -> None:
    db.add(Market(code="NASDAQ", name="NASDAQ", region=MarketRegion.US, country="US",
                  currency="USD", ticker_suffix=""))
    db.add(Market(code="PSX", name="PSX", region=MarketRegion.PSX, country="PK",
                  currency="PKR", ticker_suffix=".KA"))
    db.flush()
    us = db.scalar(select(Market).where(Market.code == "NASDAQ"))
    psx = db.scalar(select(Market).where(Market.code == "PSX"))
    db.add(Security(market_id=us.id, symbol="AAPL", provider_symbol="AAPL",
                    asset_class=AssetClass.EQUITY, currency="USD"))
    db.add(Security(market_id=psx.id, symbol="LUCK", provider_symbol="LUCK.KA",
                    asset_class=AssetClass.EQUITY, currency="PKR"))
    db.commit()


def test_ingest_sets_summary_and_skips_psx(db: Session) -> None:
    _seed(db)
    f = _Fetcher()
    result = ingest_profiles(db, f)
    assert result["securities"] == 1  # PSX excluded from the query entirely
    assert f.calls == ["AAPL"]
    aapl = db.scalar(select(Security).where(Security.provider_symbol == "AAPL"))
    assert aapl.long_business_summary == "Acme makes anvils and rockets."


def test_ingest_is_resumable(db: Session) -> None:
    _seed(db)
    ingest_profiles(db, _Fetcher())
    f2 = _Fetcher()
    ingest_profiles(db, f2)  # already populated → no refetch
    assert f2.calls == []
