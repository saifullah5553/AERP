from __future__ import annotations

from datetime import date

from app.ingestion.estimates import ingest_for_security, normalize
from app.models.enums import AssetClass, MarketRegion
from app.models.market import Market, Security
from sqlalchemy import select
from sqlalchemy.orm import Session

RAW = {
    "calendar": {"Earnings Date": [date(2026, 7, 31), date(2026, 6, 1)]},
    "earnings_estimate": {"0q": {"avg": 2.45, "numberOfAnalysts": 27, "growth": 0.08}},
    "revenue_estimate": {"0q": {"avg": 1.2e11}},
    "eps_revisions": {"0q": {"upLast30days": 5, "downLast30days": 1}},
}


def test_normalize_picks_upcoming_date_and_fields() -> None:
    s = normalize(RAW, today=date(2026, 6, 15))
    assert s.next_earnings_date == date(2026, 7, 31)  # earliest upcoming, not the past one
    assert s.eps_avg == 2.45
    assert s.eps_num == 27
    assert abs((s.eps_growth or 0) - 0.08) < 1e-9
    assert s.rev_avg == 1.2e11
    assert s.eps_up_30d == 5 and s.eps_down_30d == 1


def test_normalize_empty() -> None:
    assert normalize({}, today=date(2026, 6, 15)).is_empty()


class _Fetcher:
    def raw(self, provider_symbol: str):
        return RAW


def test_ingest_sets_columns(db: Session) -> None:
    db.add(Market(code="NASDAQ", name="NASDAQ", region=MarketRegion.US, country="US",
                  currency="USD", ticker_suffix=""))
    db.add(Security(market_id=1, symbol="AAPL", provider_symbol="AAPL",
                    asset_class=AssetClass.EQUITY, currency="USD"))
    db.commit()
    sec = db.scalar(select(Security))
    assert ingest_for_security(db, _Fetcher(), sec) is True
    db.commit()
    sec = db.scalar(select(Security))
    assert sec.eps_estimate_avg == 2.45
    assert sec.eps_estimate_num == 27
    assert sec.eps_revisions_up_30d == 5
