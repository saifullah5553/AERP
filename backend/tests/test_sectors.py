from __future__ import annotations

from datetime import date

from app.models.enums import AssetClass, MarketRegion, StatementPeriod
from app.models.fundamentals import FinancialRatios
from app.models.market import Market, Security
from app.models.scoring import Score
from app.services.sectors import build_sector_stats
from sqlalchemy import select
from sqlalchemy.orm import Session


def _seed(db: Session) -> None:
    db.add(Market(code="PSX", name="PSX", region=MarketRegion.PSX, country="PK",
                  currency="PKR", ticker_suffix=".KA"))
    db.commit()
    mid = db.scalar(select(Market)).id
    # 3 cement names + 2 banks so both sectors qualify (>=2).
    rows = [("LUCK", "CEMENT", 80, 0.20), ("DGKC", "CEMENT", 70, 0.16),
            ("CHCC", "CEMENT", 60, 0.14), ("MCB", "COMMERCIAL BANKS", 55, 0.18),
            ("HBL", "COMMERCIAL BANKS", 50, 0.17)]
    for i, (sym, sector, comp, roe) in enumerate(rows, 1):
        db.add(Security(id=i, market_id=mid, symbol=sym, provider_symbol=f"{sym}.KA",
                        asset_class=AssetClass.EQUITY, sector=sector, currency="PKR"))
        db.add(Score(security_id=i, as_of=date(2026, 3, 31), composite=comp,
                     technical=comp, fundamental=comp))
        db.add(FinancialRatios(security_id=i, period=StatementPeriod.ANNUAL,
                               fiscal_date=date(2026, 3, 31), roe=roe))
    db.commit()


def test_build_sector_stats(db: Session) -> None:
    _seed(db)
    stats = build_sector_stats(db)
    assert "psx" in stats
    sectors = {s["sector"]: s for s in stats["psx"]}
    assert "CEMENT" in sectors and "COMMERCIAL BANKS" in sectors
    cement = sectors["CEMENT"]
    assert cement["count"] == 3
    assert cement["score"] == 70.0  # avg of 80/70/60
    assert cement["medians"]["roe"] == 0.16  # median of 0.20/0.16/0.14
    # sorted by score desc → cement (70) before banks (52.5)
    assert stats["psx"][0]["sector"] == "CEMENT"


def test_singletons_excluded(db: Session) -> None:
    db.add(Market(code="PSX", name="PSX", region=MarketRegion.PSX, country="PK",
                  currency="PKR", ticker_suffix=".KA"))
    db.commit()
    db.add(Security(market_id=1, symbol="X", provider_symbol="X.KA",
                    asset_class=AssetClass.EQUITY, sector="LONE", currency="PKR"))
    db.commit()
    sid = db.scalar(select(Security)).id
    db.add(Score(security_id=sid, as_of=date(2026, 3, 31), composite=90))
    db.commit()
    stats = build_sector_stats(db)
    # single-name sector is dropped (needs >=2)
    assert all(s["sector"] != "LONE" for s in stats.get("psx", []))
