from __future__ import annotations

from datetime import date

from app.ingestion.ttm import build_ttm_for_security
from app.models.enums import AssetClass, MarketRegion, StatementPeriod
from app.models.fundamentals import BalanceSheet, IncomeStatement
from app.models.market import Market, Security
from sqlalchemy import select
from sqlalchemy.orm import Session


def _seed(db: Session) -> int:
    db.add(Market(code="NASDAQ", name="NASDAQ", region=MarketRegion.US, country="US",
                  currency="USD", ticker_suffix=""))
    db.add(Security(market_id=1, symbol="AAPL", provider_symbol="AAPL",
                    asset_class=AssetClass.EQUITY, currency="USD"))
    db.commit()
    sid = db.scalar(select(Security)).id
    # 5 quarters of income (revenue/net_income) + balance snapshots
    q = [
        (date(2025, 3, 31), 100, 10), (date(2025, 6, 30), 110, 11),
        (date(2025, 9, 30), 120, 12), (date(2025, 12, 31), 130, 13),
        (date(2026, 3, 31), 140, 14),
    ]
    for d, rev, ni in q:
        db.add(IncomeStatement(security_id=sid, period=StatementPeriod.QUARTER,
                               fiscal_date=d, revenue=rev, net_income=ni))
        db.add(BalanceSheet(security_id=sid, period=StatementPeriod.QUARTER,
                            fiscal_date=d, total_assets=rev * 5))
    db.commit()
    return sid


def test_ttm_sums_flows_and_snapshots_balance(db: Session) -> None:
    sid = _seed(db)
    build_ttm_for_security(db, sid)
    db.commit()

    ttm = db.scalars(
        select(IncomeStatement)
        .where(IncomeStatement.security_id == sid, IncomeStatement.period == StatementPeriod.TTM)
        .order_by(IncomeStatement.fiscal_date.asc())
    ).all()
    # 5 quarters → 2 TTM windows (ending Dec-2025 and Mar-2026)
    assert len(ttm) == 2
    latest = ttm[-1]
    assert latest.fiscal_date == date(2026, 3, 31)
    assert float(latest.revenue) == 110 + 120 + 130 + 140  # trailing 4 quarters
    assert float(latest.net_income) == 11 + 12 + 13 + 14

    # Balance carried through point-in-time (not summed).
    bal = db.scalar(
        select(BalanceSheet).where(
            BalanceSheet.security_id == sid,
            BalanceSheet.period == StatementPeriod.TTM,
            BalanceSheet.fiscal_date == date(2026, 3, 31),
        )
    )
    assert float(bal.total_assets) == 140 * 5
