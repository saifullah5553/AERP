from __future__ import annotations

from app.ingestion.universe_curated import forex_name, load_curated_universe
from app.models.enums import AssetClass, MarketRegion
from app.models.market import Market, Security
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def _markets(db: Session) -> None:
    db.add_all([
        Market(code="NSE", name="NSE", region=MarketRegion.INDIA, country="IN",
               currency="INR", ticker_suffix=".NS", is_active=True),
        Market(code="TADAWUL", name="Tadawul", region=MarketRegion.GCC, country="SA",
               currency="SAR", ticker_suffix=".SR", is_active=True),
        Market(code="QSE", name="Qatar", region=MarketRegion.GCC, country="QA",
               currency="QAR", ticker_suffix=".QA", is_active=True),
        Market(code="ASX", name="ASX", region=MarketRegion.AUSTRALIA, country="AU",
               currency="AUD", ticker_suffix=".AX", is_active=True),
        Market(code="FOREX", name="Forex", region=MarketRegion.GLOBAL, country=None,
               currency="USD", ticker_suffix="=X", is_active=True),
        Market(code="COMMODITY", name="Commodities", region=MarketRegion.GLOBAL, country=None,
               currency="USD", ticker_suffix="=F", is_active=True),
        Market(code="CRYPTO", name="Crypto", region=MarketRegion.GLOBAL, country=None,
               currency="USD", ticker_suffix="-USD", is_active=True),
    ])
    db.commit()


def test_forex_name() -> None:
    assert forex_name("EURUSD") == "Euro / US Dollar"
    assert forex_name("USDPKR") == "US Dollar / Pakistani Rupee"


def test_load_curated_universe(db: Session) -> None:
    _markets(db)
    n = load_curated_universe(db)
    assert n["india"] > 40
    assert n["gcc"] > 15
    assert n["australia"] > 20
    assert n["forex"] > 30
    assert n["commodity"] > 10
    assert n["crypto"] > 10

    # Forex securities get the =X suffix and a readable name.
    eur = db.scalar(select(Security).where(Security.symbol == "EURUSD"))
    assert eur.provider_symbol == "EURUSD=X"
    assert eur.asset_class == AssetClass.FOREX

    # Commodities have no fundamentals but are real securities.
    gold = db.scalar(select(Security).where(Security.symbol == "GC"))
    assert gold.provider_symbol == "GC=F"
    assert gold.asset_class == AssetClass.COMMODITY


def test_load_curated_is_idempotent(db: Session) -> None:
    _markets(db)
    load_curated_universe(db)
    before = db.scalar(select(func.count()).select_from(Security))
    load_curated_universe(db)
    after = db.scalar(select(func.count()).select_from(Security))
    assert before == after  # re-run enriches, never duplicates
