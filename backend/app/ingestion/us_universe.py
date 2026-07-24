"""US equity universe from the SEC (free, keyless).

The SEC publishes the full list of registered companies with tickers and their
listing exchange at ``company_tickers_exchange.json`` — ~10k rows. We load the
Nasdaq/NYSE common stocks (skipping OTC/CBOE and preferred/warrant tickers) as
securities, giving a real multi-thousand-name US universe with no manual JSON and
no API key. HTTP goes through an injectable client for testing.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.ingestion.providers.base import SecurityProfile
from app.ingestion.repository import markets_by_code, upsert_security
from app.models.enums import AssetClass

log = get_logger(__name__)

URL = "https://www.sec.gov/files/company_tickers_exchange.json"
# SEC asks for a descriptive User-Agent; requests without one are blocked.
HEADERS = {"User-Agent": "AERP equity research (contact: admin@aerp.local)"}
DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

# SEC exchange label → our market code (majors only).
EXCHANGE_MAP = {"Nasdaq": "NASDAQ", "NYSE": "NYSE"}


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
    db: Session, client: SECClient, limit: int | None = None
) -> dict[str, int]:
    entries = client.fetch()
    markets = markets_by_code(db)
    created = 0
    considered = 0
    for entry in entries:
        code = EXCHANGE_MAP.get(entry.exchange or "")
        ticker = entry.ticker.upper().strip()
        # Skip non-major exchanges and preferred/warrant/unit tickers (dots, dashes).
        if code is None or not ticker.isalnum():
            continue
        market = markets.get(code)
        if market is None:
            continue
        profile = SecurityProfile(
            symbol=ticker,
            name=entry.name.title() if entry.name else ticker,
            asset_class=AssetClass.EQUITY,
            exchange=code,
            currency="USD",
            country="US",
        )
        security, was_created = upsert_security(db, market, profile)
        if entry.cik and not security.cik:
            security.cik = f"{entry.cik:010d}"  # EDGAR uses 10-digit zero-padded CIK
        created += int(was_created)
        considered += 1
        if limit is not None and considered >= limit:
            break
    db.commit()
    result = {"discovered": len(entries), "created": created}
    log.info("ingest_us_universe: %s", result)
    return result
