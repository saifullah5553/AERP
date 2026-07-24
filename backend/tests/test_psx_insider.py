from __future__ import annotations

from datetime import date

from app.engines.insider.engine import compute_for_security
from app.ingestion.psx_insider import ingest_insider_text, parse_insider_csv
from app.models.corporate import InsiderTransaction
from app.models.enums import AssetClass, InsiderTransactionType, MarketRegion
from app.models.market import Market, Security
from sqlalchemy import func, select
from sqlalchemy.orm import Session

# Flexible headers on purpose (matches real Sarmaaya-style exports).
CSV = "\n".join([
    "Symbol,Insider Name,Designation,Date,Type,Shares,Rate",
    "LUCK,Ali Khan,Director,2026-07-10,Buy,10000,450",
    "LUCK,Sara Ahmed,CEO,2026-07-12,Sell,2000,455",
    "FFC,Bilal,Director,11-07-2026,Purchase,5000,550",
])


def _psx(db: Session) -> None:
    db.add(Market(code="PSX", name="PSX", region=MarketRegion.PSX,
                  currency="PKR", ticker_suffix=".KA"))
    db.add(Security(market_id=1, symbol="LUCK", provider_symbol="LUCK.KA",
                    name="Lucky", asset_class=AssetClass.EQUITY, currency="PKR"))
    db.commit()


def test_parse_flexible_headers() -> None:
    rows = parse_insider_csv(CSV)
    assert len(rows) == 3
    luck_buy = next(r for r in rows if r.symbol == "LUCK"
                    and r.transaction_type == InsiderTransactionType.BUY)
    assert luck_buy.insider == "Ali Khan"
    assert luck_buy.title == "Director"
    assert luck_buy.transaction_date == date(2026, 7, 10)
    assert luck_buy.shares == 10000 and luck_buy.price == 450
    assert luck_buy.value == 4_500_000
    # FFC uses DD-MM-YYYY and "Purchase" → BUY.
    ffc = next(r for r in rows if r.symbol == "FFC")
    assert ffc.transaction_type == InsiderTransactionType.BUY
    assert ffc.transaction_date == date(2026, 7, 11)


def test_portfolio360_columns() -> None:
    # Exact Portfolio360 layout, incl. a "Rs X mn" value that must fall back to
    # shares*price, and Person→insider / Role→title mapping.
    csv = "\n".join([
        "Date,Symbol,Company,Person,Role,Type,Shares,Rate,Value",
        '2026-07-24,MACTER,—,Asif Misbah,Executive,SELL,"475,000",400,Rs 190.0 mn',
        '2026-07-23,PKGS,—,SYED BABAR ALI,Executive,BUY,"21,519",785,Rs 16.9 mn',
    ])
    rows = parse_insider_csv(csv)
    assert len(rows) == 2
    macter = next(r for r in rows if r.symbol == "MACTER")
    assert macter.insider == "Asif Misbah"        # Person → insider
    assert macter.title == "Executive"            # Role → title
    assert macter.transaction_type == InsiderTransactionType.SELL
    assert macter.shares == 475000 and macter.price == 400
    assert macter.value == 475000 * 400           # "Rs 190.0 mn" unparsable → computed


def test_ingest_creates_and_is_idempotent(db: Session) -> None:
    _psx(db)
    first = ingest_insider_text(db, CSV)
    assert first["written"] == 3
    # FFC auto-created as a PSX security.
    assert db.scalar(select(Security).where(Security.provider_symbol == "FFC.KA")) is not None
    assert db.scalar(select(func.count()).select_from(InsiderTransaction)) == 3

    second = ingest_insider_text(db, CSV)  # same file again
    assert second["written"] == 0
    assert db.scalar(select(func.count()).select_from(InsiderTransaction)) == 3


def test_psx_insider_score_via_engine(db: Session) -> None:
    _psx(db)
    ingest_insider_text(db, CSV)
    luck = db.scalar(select(Security).where(Security.provider_symbol == "LUCK.KA"))

    # LUCK: 4.5M buy vs 0.91M sell → strongly net buying.
    result = compute_for_security(db, luck, window=60, as_of=date(2026, 7, 20))
    assert result.score is not None and result.score > 70
    assert result.activity in {"buying", "strong_buying"}
    assert result.buy_count == 1 and result.sell_count == 1
