from __future__ import annotations

from datetime import date

from app.engines.forex.engine import compute_for_security
from app.ingestion.macro import WorldBankClient, ingest_macro
from app.models.enums import AssetClass, MacroIndicatorType, MarketRegion
from app.models.macro import MacroIndicator
from app.models.market import Market, Security
from app.models.scoring import Score
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.mock_http import mock_client


def _security(db: Session, symbol="EURUSD") -> Security:
    market = Market(code="FOREX", name="Forex", region=MarketRegion.GLOBAL,
                    currency="USD", ticker_suffix="=X")
    db.add(market)
    db.flush()
    sec = Security(market_id=market.id, symbol=symbol, provider_symbol=f"{symbol}=X",
                   name=f"{symbol}", asset_class=AssetClass.FOREX, currency="USD")
    db.add(sec)
    db.commit()
    return sec


def _macro(db: Session, country: str, values: dict[MacroIndicatorType, float]) -> None:
    for ind, val in values.items():
        db.add(MacroIndicator(country=country, indicator=ind,
                              period_date=date(2024, 12, 31), value=val))
    db.commit()


def test_stronger_quote_makes_pair_bearish(db: Session) -> None:
    sec = _security(db, "EURUSD")
    # US strong, Euro area weaker → EUR (base) < USD (quote) → EUR/USD < 50.
    _macro(db, "US", {MacroIndicatorType.GDP_GROWTH: 3.0,
                      MacroIndicatorType.REAL_INTEREST_RATE: 2.0,
                      MacroIndicatorType.CPI_INFLATION: 2.5,
                      MacroIndicatorType.UNEMPLOYMENT: 4.0,
                      MacroIndicatorType.CURRENT_ACCOUNT: -3.0})
    _macro(db, "EMU", {MacroIndicatorType.GDP_GROWTH: 0.5,
                       MacroIndicatorType.REAL_INTEREST_RATE: 0.2,
                       MacroIndicatorType.CPI_INFLATION: 2.2,
                       MacroIndicatorType.UNEMPLOYMENT: 6.5,
                       MacroIndicatorType.CURRENT_ACCOUNT: 2.0})

    outcome = compute_for_security(db, sec)
    assert outcome.computed is True
    assert outcome.score is not None
    assert outcome.score < 50  # base weaker than quote

    score = db.scalar(select(Score).where(Score.security_id == sec.id))
    assert float(score.fundamental) == outcome.score
    assert score.breakdown["fundamental"]["type"] == "forex_macro"
    assert score.breakdown["fundamental"]["pair"] == "EUR/USD"


def test_symmetry_inverse_pair_is_bullish(db: Session) -> None:
    sec = _security(db, "USDEUR")
    _macro(db, "US", {MacroIndicatorType.GDP_GROWTH: 3.0,
                      MacroIndicatorType.REAL_INTEREST_RATE: 2.0})
    _macro(db, "EMU", {MacroIndicatorType.GDP_GROWTH: 0.5,
                       MacroIndicatorType.REAL_INTEREST_RATE: 0.2})
    outcome = compute_for_security(db, sec)
    assert outcome.score > 50  # USD (base) stronger than EUR (quote)


def test_no_macro_not_computed(db: Session) -> None:
    sec = _security(db, "EURUSD")
    outcome = compute_for_security(db, sec)
    assert outcome.computed is False
    assert outcome.score is None


def test_end_to_end_ingest_then_score(db: Session) -> None:
    sec = _security(db, "EURUSD")
    ingest_macro(db, WorldBankClient(mock_client()))
    outcome = compute_for_security(db, sec)
    assert outcome.computed is True
    assert outcome.score is not None
