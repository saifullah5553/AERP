"""US equity universe from the SEC (free, keyless).

The SEC publishes the full list of registered companies with tickers and their
listing exchange at ``company_tickers_exchange.json`` — ~10k rows. We load the
Nasdaq/NYSE common stocks (skipping OTC/CBOE and preferred/warrant tickers) as
securities, giving a real multi-thousand-name US universe with no manual JSON and
no API key. HTTP goes through an injectable client for testing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.ingestion.providers.base import SecurityProfile
from app.ingestion.repository import markets_by_code, upsert_security
from app.models.enums import AssetClass

log = get_logger(__name__)

URL = "https://www.sec.gov/files/company_tickers_exchange.json"
_SP500_PATH = Path(__file__).resolve().parent.parent / "data" / "sp500.json"


def load_sp500() -> list[dict[str, str]]:
    """S&P 500 constituents bundled at app/data/sp500.json (Yahoo-format tickers)."""
    if not _SP500_PATH.exists():
        return []
    try:
        return json.loads(_SP500_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
# SEC asks for a descriptive User-Agent; requests without one are blocked.
HEADERS = {"User-Agent": "AERP equity research (contact: admin@aerp.local)"}
DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

# SEC exchange label → our market code (majors only).
EXCHANGE_MAP = {"Nasdaq": "NASDAQ", "NYSE": "NYSE"}

# Curated US large-cap universe. Prices/fundamentals for US come from Yahoo, which
# rate-limits datacenter IPs — so we ingest a meaningful large-cap set rather than
# all ~7,000 tickers (which would be mostly dataless in the free snapshot). Names
# and exchanges still come from SEC (keyless). Yahoo symbols == plain US tickers.
US_LARGE_CAPS: tuple[str, ...] = (
    # Mega-cap tech / comms
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA", "AVGO", "ORCL",
    "ADBE", "CRM", "CSCO", "ACN", "AMD", "INTC", "QCOM", "TXN", "IBM", "NOW",
    "INTU", "AMAT", "MU", "ADI", "LRCX", "KLAC", "SNPS", "CDNS", "PANW", "NFLX",
    "DIS", "CMCSA", "T", "VZ", "TMUS",
    # Financials
    "BRK-B", "JPM", "BAC", "WFC", "GS", "MS", "C", "SCHW", "AXP", "BLK",
    "SPGI", "V", "MA", "PYPL", "COF", "USB", "PNC",
    # Healthcare
    "UNH", "JNJ", "LLY", "PFE", "MRK", "ABBV", "TMO", "ABT", "DHR", "BMY",
    "AMGN", "MDT", "GILD", "CVS", "ISRG", "VRTX", "REGN", "ZTS",
    # Consumer
    "WMT", "PG", "KO", "PEP", "COST", "MCD", "NKE", "SBUX", "HD", "LOW",
    "TGT", "BKNG", "CMG", "MDLZ", "CL", "MO", "PM",
    # Industrials / energy / materials
    "XOM", "CVX", "COP", "SLB", "EOG", "CAT", "BA", "HON", "GE", "UPS",
    "RTX", "LMT", "DE", "MMM", "UNP", "LIN", "FCX", "NEM",
    # Utilities / real estate / other
    "NEE", "DUK", "SO", "PLD", "AMT", "EQIX", "CCI",
)


@dataclass(slots=True)
class SECEntry:
    name: str
    ticker: str
    exchange: str | None
    cik: int | None = None


class SECClient:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=True)
        return self._client

    def fetch(self) -> list[SECEntry]:
        try:
            resp = self._http().get(URL, headers=HEADERS)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.warning("SEC universe fetch failed: %s", exc)
            return []
        fields = data.get("fields", [])
        rows = data.get("data", [])
        try:
            i_name, i_ticker, i_exch = (
                fields.index("name"), fields.index("ticker"), fields.index("exchange")
            )
            i_cik = fields.index("cik") if "cik" in fields else None
        except ValueError:
            return []
        out: list[SECEntry] = []
        for row in rows:
            try:
                cik = int(row[i_cik]) if i_cik is not None else None
                out.append(SECEntry(row[i_name], str(row[i_ticker]), row[i_exch], cik))
            except (IndexError, TypeError, ValueError):
                continue
        return out


def ingest_us_universe(
    db: Session,
    client: SECClient,
    limit: int | None = None,
    symbols: list[str] | None = None,
    sectors: dict[str, str] | None = None,
) -> dict[str, int]:
    """Load US securities (name/exchange/CIK) from SEC.

    ``symbols`` restricts the load to a curated allowlist (e.g. ``US_LARGE_CAPS``);
    allowlisted tickers bypass the alnum filter so names like ``BRK-B`` load. Any
    allowlisted ticker missing from SEC is created with a minimal profile so the
    curated set is always fully present.
    """
    entries = client.fetch()
    markets = markets_by_code(db)
    allow = {s.upper() for s in symbols} if symbols else None
    seen: set[str] = set()
    created = 0
    considered = 0
    for entry in entries:
        code = EXCHANGE_MAP.get(entry.exchange or "")
        ticker = entry.ticker.upper().strip()
        if code is None:
            continue
        if allow is not None:
            if ticker not in allow:
                continue
        elif not ticker.isalnum():
            # Skip preferred/warrant/unit tickers (dots, dashes) in the full load.
            continue
        market = markets.get(code)
        if market is None:
            continue
        profile = SecurityProfile(
            symbol=ticker,
            name=entry.name.title() if entry.name else ticker,
            asset_class=AssetClass.EQUITY,
            exchange=code,
            sector=(sectors or {}).get(ticker),
            currency="USD",
            country="US",
        )
        security, was_created = upsert_security(db, market, profile)
        if entry.cik and not security.cik:
            security.cik = f"{entry.cik:010d}"  # EDGAR uses 10-digit zero-padded CIK
        seen.add(ticker)
        created += int(was_created)
        considered += 1
        if limit is not None and considered >= limit:
            break

    # Ensure any curated ticker absent from SEC still exists (default to NYSE).
    if allow is not None:
        nyse = markets.get("NYSE") or markets.get("NASDAQ")
        for ticker in sorted(allow - seen):
            if nyse is None:
                break
            _, was_created = upsert_security(
                db,
                nyse,
                SecurityProfile(
                    symbol=ticker, name=ticker, asset_class=AssetClass.EQUITY,
                    exchange=nyse.code, currency="USD", country="US",
                ),
            )
            created += int(was_created)
    db.commit()
    result = {"discovered": len(entries), "created": created}
    log.info("ingest_us_universe: %s", result)
    return result
