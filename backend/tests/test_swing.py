from __future__ import annotations

from datetime import date

from app.models.enums import AssetClass, MarketRegion
from app.models.market import Market, Security
from app.models.scoring import Score
from app.services.swing import _raw_material_score, build_swing
from sqlalchemy import select
from sqlalchemy.orm import Session

RAW = {
    "sector_map": [{"keywords": ["cement"], "materials": ["NG", "CL"]}],
    "commodities": {"NG": {"trend": "decreasing"}, "CL": {"trend": "decreasing"}},
}


def test_raw_material_score() -> None:
    assert _raw_material_score("CEMENT", None, RAW) == 70.0   # both inputs falling → supportive
    assert _raw_material_score("Technology", None, RAW) is None  # no mapped inputs
    up = {"sector_map": RAW["sector_map"],
          "commodities": {"NG": {"trend": "increasing"}, "CL": {"trend": "increasing"}}}
    assert _raw_material_score("cement plant", None, up) == 40.0


def test_build_swing_blends_and_ranks(db: Session) -> None:
    db.add(Market(code="PSX", name="PSX", region=MarketRegion.PSX, country="PK",
                  currency="PKR", ticker_suffix=".KA"))
    db.commit()
    mid = db.scalar(select(Market)).id
    # Two cement names, different quality.
    for i, (sym, f, t, r) in enumerate([("LUCK", 85, 80, 70), ("WEAK", 40, 35, 45)], 1):
        db.add(Security(id=i, market_id=mid, symbol=sym, provider_symbol=f"{sym}.KA",
                        asset_class=AssetClass.EQUITY, sector="CEMENT", currency="PKR"))
        db.add(Score(security_id=i, as_of=date(2026, 3, 31), fundamental=f, technical=t,
                     risk=r, composite=(f + t) / 2))
    db.commit()

    sector_stats = {"psx": [{"sector": "CEMENT", "score": 75}]}
    regime = {"countries": {"psx": {"health": 60}}}
    out = build_swing(db, sector_stats, regime, RAW)

    assert len(out["ranked"]) == 2
    assert out["ranked"][0]["symbol"] == "LUCK"  # higher quality ranks first
    luck = out["ranked"][0]
    assert luck["catalyst"] is not None and 0 <= luck["swing_score"] <= 100
    assert out["by_symbol"]["LUCK.KA"] == luck["swing_score"]
    # non-equity / unscored excluded
    assert all(r["swing_score"] is not None for r in out["ranked"])
