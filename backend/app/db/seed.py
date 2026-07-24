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
    ("DFM", "Dubai Financial Market", MarketRegion.GCC, "AE", "AED", "Asia/Dubai", ".DU"),
    ("ADX", "Abu Dhabi Securities Exchange", MarketRegion.GCC, "AE", "AED", "Asia/Dubai", ".AD"),
    ("FOREX", "Foreign Exchange", MarketRegion.GLOBAL, None, "USD", "UTC", "=X"),
    ("CRYPTO", "Crypto Spot", MarketRegion.GLOBAL, None, "USD", "UTC", "-USD"),
    ("COMMODITY", "Commodity Futures", MarketRegion.GLOBAL, None, "USD", "UTC", "=F"),
]

# ── Securities ────────────────────────────────────────────────
# (market_code, symbol, name, asset_class, sector, industry)
SECURITIES: list[tuple] = [
    # US — NASDAQ / NYSE
    ("NASDAQ", "AAPL", "Apple Inc.", AssetClass.EQUITY, "Technology", "Consumer Electronics"),
    ("NASDAQ", "MSFT", "Microsoft Corporation", AssetClass.EQUITY, "Technology", "Software—Infrastructure"),
    ("NASDAQ", "NVDA", "NVIDIA Corporation", AssetClass.EQUITY, "Technology", "Semiconductors"),
    ("NASDAQ", "GOOGL", "Alphabet Inc.", AssetClass.EQUITY, "Communication Services", "Internet Content & Information"),
    ("NASDAQ", "AMZN", "Amazon.com, Inc.", AssetClass.EQUITY, "Consumer Cyclical", "Internet Retail"),
    ("NASDAQ", "META", "Meta Platforms, Inc.", AssetClass.EQUITY, "Communication Services", "Internet Content & Information"),
    ("NASDAQ", "TSLA", "Tesla, Inc.", AssetClass.EQUITY, "Consumer Cyclical", "Auto Manufacturers"),
    ("NASDAQ", "AMD", "Advanced Micro Devices, Inc.", AssetClass.EQUITY, "Technology", "Semiconductors"),
    ("NASDAQ", "AVGO", "Broadcom Inc.", AssetClass.EQUITY, "Technology", "Semiconductors"),
    ("NASDAQ", "NFLX", "Netflix, Inc.", AssetClass.EQUITY, "Communication Services", "Entertainment"),
    ("NYSE", "JPM", "JPMorgan Chase & Co.", AssetClass.EQUITY, "Financial Services", "Banks—Diversified"),
    ("NYSE", "V", "Visa Inc.", AssetClass.EQUITY, "Financial Services", "Credit Services"),
    ("NYSE", "WMT", "Walmart Inc.", AssetClass.EQUITY, "Consumer Defensive", "Discount Stores"),
    ("NYSE", "XOM", "Exxon Mobil Corporation", AssetClass.EQUITY, "Energy", "Oil & Gas Integrated"),
    ("NYSE", "CVX", "Chevron Corporation", AssetClass.EQUITY, "Energy", "Oil & Gas Integrated"),

    # Pakistan — PSX
    ("PSX", "LUCK", "Lucky Cement Limited", AssetClass.EQUITY, "Materials", "Cement"),
    ("PSX", "SYS", "Systems Limited", AssetClass.EQUITY, "Technology", "IT Services"),
    ("PSX", "ENGRO", "Engro Corporation Limited", AssetClass.EQUITY, "Materials", "Conglomerate"),
    ("PSX", "HUBC", "Hub Power Company Limited", AssetClass.EQUITY, "Utilities", "Independent Power Producer"),
    ("PSX", "OGDC", "Oil & Gas Development Company", AssetClass.EQUITY, "Energy", "Oil & Gas E&P"),
    ("PSX", "PPL", "Pakistan Petroleum Limited", AssetClass.EQUITY, "Energy", "Oil & Gas E&P"),
    ("PSX", "MCB", "MCB Bank Limited", AssetClass.EQUITY, "Financial Services", "Banks"),
    ("PSX", "UBL", "United Bank Limited", AssetClass.EQUITY, "Financial Services", "Banks"),
    ("PSX", "MEBL", "Meezan Bank Limited", AssetClass.EQUITY, "Financial Services", "Islamic Banking"),
    ("PSX", "FFC", "Fauji Fertilizer Company", AssetClass.EQUITY, "Materials", "Fertilizers"),

    # India — NSE
    ("NSE", "RELIANCE", "Reliance Industries Limited", AssetClass.EQUITY, "Energy", "Conglomerate"),
    ("NSE", "TCS", "Tata Consultancy Services", AssetClass.EQUITY, "Technology", "IT Services"),
    ("NSE", "INFY", "Infosys Limited", AssetClass.EQUITY, "Technology", "IT Services"),
    ("NSE", "HDFCBANK", "HDFC Bank Limited", AssetClass.EQUITY, "Financial Services", "Banks"),
    ("NSE", "ICICIBANK", "ICICI Bank Limited", AssetClass.EQUITY, "Financial Services", "Banks"),
    ("NSE", "SBIN", "State Bank of India", AssetClass.EQUITY, "Financial Services", "Banks"),
    ("NSE", "ITC", "ITC Limited", AssetClass.EQUITY, "Consumer Defensive", "Tobacco & FMCG"),

    # GCC — Tadawul / DFM / ADX
    ("TADAWUL", "2222", "Saudi Arabian Oil Company (Aramco)", AssetClass.EQUITY, "Energy", "Oil & Gas Integrated"),
    ("TADAWUL", "1120", "Al Rajhi Bank", AssetClass.EQUITY, "Financial Services", "Islamic Banking"),
    ("TADAWUL", "2010", "Saudi Basic Industries Corp (SABIC)", AssetClass.EQUITY, "Materials", "Chemicals"),
    ("DFM", "EMAAR", "Emaar Properties PJSC", AssetClass.EQUITY, "Real Estate", "Real Estate Development"),
    ("DFM", "DEWA", "Dubai Electricity & Water Authority", AssetClass.EQUITY, "Utilities", "Utilities—Diversified"),
    ("ADX", "FAB", "First Abu Dhabi Bank", AssetClass.EQUITY, "Financial Services", "Banks"),
    ("ADX", "ALDAR", "Aldar Properties PJSC", AssetClass.EQUITY, "Real Estate", "Real Estate Development"),

    # Crypto
    ("CRYPTO", "BTC", "Bitcoin", AssetClass.CRYPTO, None, None),
    ("CRYPTO", "ETH", "Ethereum", AssetClass.CRYPTO, None, None),
    ("CRYPTO", "SOL", "Solana", AssetClass.CRYPTO, None, None),
    ("CRYPTO", "BNB", "BNB", AssetClass.CRYPTO, None, None),
    ("CRYPTO", "XRP", "XRP", AssetClass.CRYPTO, None, None),

    # Forex
    ("FOREX", "EURUSD", "Euro / US Dollar", AssetClass.FOREX, None, None),
    ("FOREX", "GBPUSD", "British Pound / US Dollar", AssetClass.FOREX, None, None),
    ("FOREX", "USDJPY", "US Dollar / Japanese Yen", AssetClass.FOREX, None, None),

    # Commodities
    ("COMMODITY", "GC", "Gold Futures", AssetClass.COMMODITY, None, None),
    ("COMMODITY", "CL", "Crude Oil WTI Futures", AssetClass.COMMODITY, None, None),
    ("COMMODITY", "SI", "Silver Futures", AssetClass.COMMODITY, None, None),
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
