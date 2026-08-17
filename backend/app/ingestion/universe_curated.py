"""Curated multi-market universe loader (free / keyless via Yahoo symbols).

Prices, history, and (for equities) fundamentals come from Yahoo (`yfinance`),
which works from a residential IP but rate-limits datacenter IPs. So we load
curated large-cap sets per market plus the full forex/commodity/crypto lists,
rather than every ticker on every exchange. Each entry maps to a seeded Market by
code; ``upsert_security`` attaches it with the market's Yahoo ticker suffix
(e.g. ``.NS``, ``.SR``, ``.AX``, ``=X``, ``=F``, ``-USD``).

Only markets with confirmed free Yahoo data are here: US, India (NSE), GCC
(Saudi Tadawul + Qatar), Australia (ASX), forex, commodities, crypto. Dubai/Abu
Dhabi are intentionally excluded (Yahoo returns nothing for .DU/.AD).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.ingestion.repository import SecurityProfile, markets_by_code, upsert_security
from app.models.enums import AssetClass

log = get_logger(__name__)


# ── India (NSE) — Nifty large/mid caps ──────────────────────────────────────
INDIA_NSE: tuple[tuple[str, str, str], ...] = (
    ("RELIANCE", "Reliance Industries", "Energy"),
    ("TCS", "Tata Consultancy Services", "Technology"),
    ("HDFCBANK", "HDFC Bank", "Financial Services"),
    ("ICICIBANK", "ICICI Bank", "Financial Services"),
    ("INFY", "Infosys", "Technology"),
    ("SBIN", "State Bank of India", "Financial Services"),
    ("BHARTIARTL", "Bharti Airtel", "Communication Services"),
    ("ITC", "ITC", "Consumer Defensive"),
    ("HINDUNILVR", "Hindustan Unilever", "Consumer Defensive"),
    ("LT", "Larsen & Toubro", "Industrials"),
    ("KOTAKBANK", "Kotak Mahindra Bank", "Financial Services"),
    ("AXISBANK", "Axis Bank", "Financial Services"),
    ("BAJFINANCE", "Bajaj Finance", "Financial Services"),
    ("ASIANPAINT", "Asian Paints", "Materials"),
    ("MARUTI", "Maruti Suzuki", "Consumer Cyclical"),
    ("HCLTECH", "HCL Technologies", "Technology"),
    ("SUNPHARMA", "Sun Pharmaceutical", "Healthcare"),
    ("TITAN", "Titan Company", "Consumer Cyclical"),
    ("ULTRACEMCO", "UltraTech Cement", "Materials"),
    ("WIPRO", "Wipro", "Technology"),
    ("NESTLEIND", "Nestle India", "Consumer Defensive"),
    ("ONGC", "Oil & Natural Gas Corp", "Energy"),
    ("NTPC", "NTPC", "Utilities"),
    ("POWERGRID", "Power Grid Corp", "Utilities"),
    ("TATAMOTORS", "Tata Motors", "Consumer Cyclical"),
    ("TATASTEEL", "Tata Steel", "Materials"),
    ("ADANIENT", "Adani Enterprises", "Industrials"),
    ("ADANIPORTS", "Adani Ports & SEZ", "Industrials"),
    ("COALINDIA", "Coal India", "Energy"),
    ("BAJAJFINSV", "Bajaj Finserv", "Financial Services"),
    ("HDFCLIFE", "HDFC Life Insurance", "Financial Services"),
    ("SBILIFE", "SBI Life Insurance", "Financial Services"),
    ("GRASIM", "Grasim Industries", "Materials"),
    ("HINDALCO", "Hindalco Industries", "Materials"),
    ("JSWSTEEL", "JSW Steel", "Materials"),
    ("DRREDDY", "Dr. Reddy's Laboratories", "Healthcare"),
    ("CIPLA", "Cipla", "Healthcare"),
    ("DIVISLAB", "Divi's Laboratories", "Healthcare"),
    ("EICHERMOT", "Eicher Motors", "Consumer Cyclical"),
    ("BRITANNIA", "Britannia Industries", "Consumer Defensive"),
    ("HEROMOTOCO", "Hero MotoCorp", "Consumer Cyclical"),
    ("BAJAJ-AUTO", "Bajaj Auto", "Consumer Cyclical"),
    ("M&M", "Mahindra & Mahindra", "Consumer Cyclical"),
    ("TECHM", "Tech Mahindra", "Technology"),
    ("INDUSINDBK", "IndusInd Bank", "Financial Services"),
    ("APOLLOHOSP", "Apollo Hospitals", "Healthcare"),
    ("TATACONSUM", "Tata Consumer Products", "Consumer Defensive"),
    ("BPCL", "Bharat Petroleum", "Energy"),
    ("PIDILITIND", "Pidilite Industries", "Materials"),
    ("DMART", "Avenue Supermarts", "Consumer Defensive"),
)

# ── GCC — Saudi Tadawul (numeric) + Qatar (QSE) ─────────────────────────────
GCC_TADAWUL: tuple[tuple[str, str, str], ...] = (
    ("2222", "Saudi Aramco", "Energy"),
    ("1120", "Al Rajhi Bank", "Financial Services"),
    ("2010", "SABIC", "Materials"),
    ("7010", "stc (Saudi Telecom)", "Communication Services"),
    ("1180", "Saudi National Bank", "Financial Services"),
    ("2350", "Saudi Kayan Petrochemical", "Materials"),
    ("1211", "Maaden (Saudi Arabian Mining)", "Materials"),
    ("2280", "Almarai", "Consumer Defensive"),
    ("1150", "Alinma Bank", "Financial Services"),
    ("1010", "Riyad Bank", "Financial Services"),
    ("4030", "Bahri (National Shipping)", "Industrials"),
    ("2020", "SABIC Agri-Nutrients", "Materials"),
    ("4013", "Dr. Sulaiman Al Habib", "Healthcare"),
    ("1060", "Saudi British Bank (SABB)", "Financial Services"),
    ("4001", "Abdullah Al Othaim Markets", "Consumer Defensive"),
)
GCC_QSE: tuple[tuple[str, str, str], ...] = (
    ("QNBK", "Qatar National Bank", "Financial Services"),
    ("QIBK", "Qatar Islamic Bank", "Financial Services"),
    ("IQCD", "Industries Qatar", "Industrials"),
    ("MARK", "Masraf Al Rayan", "Financial Services"),
    ("QEWS", "Qatar Electricity & Water", "Utilities"),
    ("ORDS", "Ooredoo", "Communication Services"),
    ("QFLS", "Qatar Fuel (Woqod)", "Energy"),
    ("CBQK", "Commercial Bank of Qatar", "Financial Services"),
)

# ── Australia (ASX) — large caps ────────────────────────────────────────────
AUSTRALIA_ASX: tuple[tuple[str, str, str], ...] = (
    ("BHP", "BHP Group", "Materials"),
    ("CBA", "Commonwealth Bank", "Financial Services"),
    ("CSL", "CSL", "Healthcare"),
    ("NAB", "National Australia Bank", "Financial Services"),
    ("WBC", "Westpac Banking", "Financial Services"),
    ("ANZ", "ANZ Group", "Financial Services"),
    ("WES", "Wesfarmers", "Consumer Cyclical"),
    ("MQG", "Macquarie Group", "Financial Services"),
    ("FMG", "Fortescue", "Materials"),
    ("WOW", "Woolworths Group", "Consumer Defensive"),
    ("TLS", "Telstra Group", "Communication Services"),
    ("RIO", "Rio Tinto", "Materials"),
    ("GMG", "Goodman Group", "Real Estate"),
    ("TCL", "Transurban Group", "Industrials"),
    ("WDS", "Woodside Energy", "Energy"),
    ("ALL", "Aristocrat Leisure", "Consumer Cyclical"),
    ("COL", "Coles Group", "Consumer Defensive"),
    ("STO", "Santos", "Energy"),
    ("QAN", "Qantas Airways", "Industrials"),
    ("REA", "REA Group", "Communication Services"),
    ("XRO", "Xero", "Technology"),
    ("SUN", "Suncorp Group", "Financial Services"),
    ("ORG", "Origin Energy", "Utilities"),
    ("COH", "Cochlear", "Healthcare"),
    ("JHX", "James Hardie", "Materials"),
)

# ── Forex — majors, crosses, and key EM pairs (all vs each base) ─────────────
_CCY = {
    "EUR": "Euro", "USD": "US Dollar", "GBP": "British Pound", "JPY": "Japanese Yen",
    "CHF": "Swiss Franc", "AUD": "Australian Dollar", "CAD": "Canadian Dollar",
    "NZD": "New Zealand Dollar", "CNY": "Chinese Yuan", "INR": "Indian Rupee",
    "PKR": "Pakistani Rupee", "SAR": "Saudi Riyal", "AED": "UAE Dirham",
    "QAR": "Qatari Riyal", "ZAR": "South African Rand", "SGD": "Singapore Dollar",
    "HKD": "Hong Kong Dollar", "TRY": "Turkish Lira", "MXN": "Mexican Peso",
    "BRL": "Brazilian Real",
}
FOREX_PAIRS: tuple[str, ...] = (
    # Majors
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD",
    # EUR crosses
    "EURGBP", "EURJPY", "EURCHF", "EURAUD", "EURCAD", "EURNZD",
    # GBP crosses
    "GBPJPY", "GBPCHF", "GBPAUD", "GBPCAD",
    # JPY / other crosses
    "AUDJPY", "CADJPY", "CHFJPY", "NZDJPY", "AUDNZD", "AUDCAD",
    # USD vs EM / regional
    "USDINR", "USDPKR", "USDCNY", "USDSAR", "USDAED", "USDQAR",
    "USDZAR", "USDSGD", "USDHKD", "USDTRY", "USDMXN", "USDBRL",
)

# ── Commodities (Yahoo continuous futures ``=F``) ───────────────────────────
COMMODITIES: tuple[tuple[str, str, str], ...] = (
    ("GC", "Gold", "Precious Metals"),
    ("SI", "Silver", "Precious Metals"),
    ("PL", "Platinum", "Precious Metals"),
    ("PA", "Palladium", "Precious Metals"),
    ("HG", "Copper", "Industrial Metals"),
    ("CL", "Crude Oil (WTI)", "Energy"),
    ("BZ", "Brent Crude", "Energy"),
    ("NG", "Natural Gas", "Energy"),
    ("RB", "Gasoline (RBOB)", "Energy"),
    ("HO", "Heating Oil", "Energy"),
    ("ZC", "Corn", "Agriculture"),
    ("ZW", "Wheat", "Agriculture"),
    ("ZS", "Soybeans", "Agriculture"),
    ("KC", "Coffee", "Agriculture"),
    ("SB", "Sugar", "Agriculture"),
    ("CC", "Cocoa", "Agriculture"),
    ("CT", "Cotton", "Agriculture"),
    ("LE", "Live Cattle", "Agriculture"),
)

# ── Market indices (Yahoo ``^`` symbols; technical-only, no fundamentals) ────
INDICES: tuple[tuple[str, str], ...] = (
    ("^GSPC", "S&P 500"), ("^IXIC", "NASDAQ Composite"), ("^DJI", "Dow Jones Industrial Average"),
    ("^RUT", "Russell 2000"), ("^NSEI", "NIFTY 50"), ("^BSESN", "BSE SENSEX"),
    ("^AXJO", "S&P/ASX 200"), ("^FTSE", "FTSE 100"), ("^N225", "Nikkei 225"),
    ("^HSI", "Hang Seng"), ("^GDAXI", "DAX"), ("^TASI.SR", "Tadawul All Share (TASI)"),
    # Pakistan and Dubai. Both were missing while their MARKETS were live, and the cost was not
    # a blank tile: the regime engine refreshes a market's index trend by looking up its index
    # ROW in this snapshot, so with no row the merge kept whatever was last written by hand.
    # PSX's index trend sat at Portfolio360's 26 Jul reading for three weeks, and Dubai had no
    # index signal at all - its "regime" was its average composite score and nothing else.
    # Neither needs a new fetch: both are already in data/prices/global.json.gz.
    ("^KSE100", "KSE-100"), ("DFMGI.AE", "DFM General Index"),
)

# ── ETFs: none, deliberately ────────────────────────────────────────────────
# We used to carry fourteen (SPY, QQQ, GLD, ARKK...). A fund files no statements of its own, so
# every one of them was a permanent blank in the fundamental score - technical-only rows in a
# platform whose whole point is the fundamentals. The exposure they stood for is better read
# from the index rows we already keep, or from the holdings themselves.
#
# Kept as an empty tuple rather than deleted so the loop below still has something to name, and
# so this note sits where the next person looks for the list. `exclusions.KEEP_ASSET_CLASSES`
# is the enforcement - it drops any ETF row at export however it got in.
ETFS: tuple[tuple[str, str, str], ...] = ()

# ── Crypto (Yahoo ``-USD``) ─────────────────────────────────────────────────
CRYPTO: tuple[tuple[str, str], ...] = (
    ("BTC", "Bitcoin"), ("ETH", "Ethereum"), ("BNB", "BNB"), ("SOL", "Solana"),
    ("XRP", "XRP"), ("ADA", "Cardano"), ("DOGE", "Dogecoin"), ("TRX", "TRON"),
    ("AVAX", "Avalanche"), ("LINK", "Chainlink"), ("DOT", "Polkadot"),
    ("MATIC", "Polygon"), ("LTC", "Litecoin"), ("BCH", "Bitcoin Cash"),
    ("XLM", "Stellar"), ("ATOM", "Cosmos"),
    ("ETC", "Ethereum Classic"), ("FIL", "Filecoin"), ("APT", "Aptos"),
)


def _add(db: Session, market, symbol, name, asset_class, sector=None):
    _, created = upsert_security(
        db,
        market,
        SecurityProfile(
            symbol=symbol,
            name=name,
            asset_class=asset_class,
            exchange=market.code,
            sector=sector,
            currency=market.currency,
            country=market.country,
        ),
    )
    return int(created)


def forex_name(pair: str) -> str:
    base, quote = pair[:3], pair[3:]
    return f"{_CCY.get(base, base)} / {_CCY.get(quote, quote)}"


def load_curated_universe(db: Session) -> dict[str, int]:
    """Create/enrich every curated security across all free-data markets."""
    m = markets_by_code(db)
    n = {"india": 0, "gcc": 0, "australia": 0, "forex": 0, "commodity": 0,
         "crypto": 0, "index": 0, "etf": 0}

    # US is loaded separately via SEC (us_universe.py) for accurate exchange/CIK.
    for code, table, key in (("NSE", INDIA_NSE, "india"), ("TADAWUL", GCC_TADAWUL, "gcc"),
                             ("QSE", GCC_QSE, "gcc"), ("ASX", AUSTRALIA_ASX, "australia")):
        market = m.get(code)
        if market is None:
            continue
        for sym, name, sector in table:
            n[key] += _add(db, market, sym, name, AssetClass.EQUITY, sector)

    forex = m.get("FOREX")
    if forex is not None:
        for pair in FOREX_PAIRS:
            n["forex"] += _add(db, forex, pair, forex_name(pair), AssetClass.FOREX)

    commodity = m.get("COMMODITY")
    if commodity is not None:
        for sym, name, sector in COMMODITIES:
            n["commodity"] += _add(db, commodity, sym, name, AssetClass.COMMODITY, sector)

    crypto = m.get("CRYPTO")
    if crypto is not None:
        for sym, name in CRYPTO:
            n["crypto"] += _add(db, crypto, sym, name, AssetClass.CRYPTO)

    index = m.get("INDEX")
    if index is not None:
        for sym, name in INDICES:
            n["index"] += _add(db, index, sym, name, AssetClass.INDEX)

    etf = m.get("ETF")
    if etf is not None:
        for sym, name, sector in ETFS:
            n["etf"] += _add(db, etf, sym, name, AssetClass.ETF, sector)

    db.commit()
    log.info("load_curated_universe: %s", n)
    return n
