"""Idempotent reference-data seed.

Seeds **markets** and a curated set of **real security identities** (symbol, name,
sector, asset class). It deliberately does NOT write prices, fundamentals, or
scores — those are computed from real data by the Phase 2 ingestion engine and the
analytics engines. Until then the screener honestly shows NULLs for those columns
rather than fabricating numbers.

Safe to run repeatedly: existing rows are matched by natural key and left alone.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.db.session import session_scope
from app.models.enums import AssetClass, MarketRegion
from app.models.market import Market, Security

log = get_logger(__name__)

# ── Markets ───────────────────────────────────────────────────
# (code, name, region, country, currency, timezone, ticker_suffix)
MARKETS: list[tuple] = [
    ("NASDAQ", "NASDAQ Stock Market", MarketRegion.US, "US", "USD", "America/New_York", ""),
    ("NYSE", "New York Stock Exchange", MarketRegion.US, "US", "USD", "America/New_York", ""),
    ("AMEX", "NYSE American", MarketRegion.US, "US", "USD", "America/New_York", ""),
    ("PSX", "Pakistan Stock Exchange", MarketRegion.PSX, "PK", "PKR", "Asia/Karachi", ".KA"),
    ("NSE", "National Stock Exchange of India", MarketRegion.INDIA, "IN", "INR", "Asia/Kolkata", ".NS"),
    ("BSE", "Bombay Stock Exchange", MarketRegion.INDIA, "IN", "INR", "Asia/Kolkata", ".BO"),
    ("TADAWUL", "Saudi Exchange (Tadawul)", MarketRegion.GCC, "SA", "SAR", "Asia/Riyadh", ".SR"),
    ("QSE", "Qatar Stock Exchange", MarketRegion.GCC, "QA", "QAR", "Asia/Qatar", ".QA"),
    # Dubai (.DU) and Abu Dhabi (.AD) dropped — no free Yahoo data.
    ("ASX", "Australian Securities Exchange", MarketRegion.AUSTRALIA, "AU", "AUD", "Australia/Sydney", ".AX"),
    ("FOREX", "Foreign Exchange", MarketRegion.GLOBAL, None, "USD", "UTC", "=X"),
    ("CRYPTO", "Crypto Spot", MarketRegion.GLOBAL, None, "USD", "UTC", "-USD"),
    ("COMMODITY", "Commodity Futures", MarketRegion.GLOBAL, None, "USD", "UTC", "=F"),
]

# ── Securities ────────────────────────────────────────────────
# (market_code, symbol, name, asset_class, sector, industry)
# Only a few PSX demo names are seeded (they're matched/enriched by the PSX CSV
# ingest). Every other market is owned by the universe loaders:
#   US → us_universe (SEC + S&P 500);  India/GCC/Australia/forex/commodity/crypto
#   → universe_curated. Seeding them here too would create cross-market duplicates.
SECURITIES: list[tuple] = [
    # Pakistan — PSX (enriched by the stockanalysis CSV ingest)
    ("PSX", "LUCK", "Lucky Cement Limited", AssetClass.EQUITY, "Materials", "Cement"),
    ("PSX", "SYS", "Systems Limited", AssetClass.EQUITY, "Technology", "IT Services"),
    ("PSX", "HUBC", "Hub Power Company Limited", AssetClass.EQUITY, "Utilities", "Independent Power Producer"),
    ("PSX", "OGDC", "Oil & Gas Development Company", AssetClass.EQUITY, "Energy", "Oil & Gas E&P"),
    ("PSX", "PPL", "Pakistan Petroleum Limited", AssetClass.EQUITY, "Energy", "Oil & Gas E&P"),
    ("PSX", "MCB", "MCB Bank Limited", AssetClass.EQUITY, "Financial Services", "Banks"),
    ("PSX", "UBL", "United Bank Limited", AssetClass.EQUITY, "Financial Services", "Banks"),
    ("PSX", "MEBL", "Meezan Bank Limited", AssetClass.EQUITY, "Financial Services", "Islamic Banking"),
    ("PSX", "FFC", "Fauji Fertilizer Company", AssetClass.EQUITY, "Materials", "Fertilizers"),
]


def _provider_symbol(symbol: str, suffix: str) -> str:
    """Build the provider-qualified symbol.

    FX pairs already embed both currencies before the ``=X`` suffix; everything
    else is ``SYMBOL + suffix`` (e.g. ``LUCK`` + ``.KA`` → ``LUCK.KA``).
    """
    return f"{symbol}{suffix}"


def seed_all() -> dict[str, int]:
    """Seed markets and securities. Returns counts of rows inserted."""
    inserted = {"markets": 0, "securities": 0}

    with session_scope() as db:
        code_to_market: dict[str, Market] = {}

        for code, name, region, country, currency, tz, suffix in MARKETS:
            market = db.query(Market).filter_by(code=code).one_or_none()
            if market is None:
                market = Market(
                    code=code,
                    name=name,
                    region=region,
                    country=country,
                    currency=currency,
                    timezone=tz,
                    ticker_suffix=suffix,
                    is_active=True,
                )
                db.add(market)
                db.flush()  # assign PK for FK use below
                inserted["markets"] += 1
            code_to_market[code] = market

        for market_code, symbol, name, asset_class, sector, industry in SECURITIES:
            market = code_to_market[market_code]
            provider_symbol = _provider_symbol(symbol, market.ticker_suffix)
            exists = (
                db.query(Security.id)
                .filter_by(market_id=market.id, symbol=symbol)
                .first()
            )
            if exists is None:
                db.add(
                    Security(
                        market_id=market.id,
                        symbol=symbol,
                        provider_symbol=provider_symbol,
                        name=name,
                        asset_class=asset_class,
                        sector=sector,
                        industry=industry,
                        currency=market.currency,
                        country=market.country,
                        is_active=True,
                    )
                )
                inserted["securities"] += 1

    log.info(
        "Seed complete: +%d markets, +%d securities",
        inserted["markets"],
        inserted["securities"],
    )
    return inserted


if __name__ == "__main__":  # pragma: no cover
    seed_all()
