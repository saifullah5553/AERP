"""Macro-economic ingestion from the World Bank API (free, keyless).

The World Bank Indicators API needs no key and returns annual series per country.
These indicators are the 'fundamentals' for forex: a currency's strength is a
function of its economy (growth, inflation, rates, jobs, external balance).

HTTP goes through an injectable ``httpx.Client`` so tests drive it with a mock
transport (no network).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.enums import AssetClass, MacroIndicatorType
from app.models.macro import MacroIndicator
from app.models.market import Security

log = get_logger(__name__)

BASE_URL = "https://api.worldbank.org/v2"
DEFAULT_TIMEOUT = httpx.Timeout(15.0, connect=8.0)

# Our indicator → World Bank series code.
WB_CODES: dict[MacroIndicatorType, str] = {
    MacroIndicatorType.GDP_GROWTH: "NY.GDP.MKTP.KD.ZG",
    MacroIndicatorType.CPI_INFLATION: "FP.CPI.TOTL.ZG",
    MacroIndicatorType.REAL_INTEREST_RATE: "FR.INR.RINR",
    MacroIndicatorType.UNEMPLOYMENT: "SL.UEM.TOTL.ZS",
    MacroIndicatorType.CURRENT_ACCOUNT: "BN.CAB.XOKA.GD.ZS",
}

# ISO-4217 currency → World Bank country code (EMU = Euro area aggregate).
CURRENCY_COUNTRY: dict[str, str] = {
    "USD": "US", "EUR": "EMU", "GBP": "GB", "JPY": "JP", "AUD": "AU", "CAD": "CA",
    "CHF": "CH", "INR": "IN", "PKR": "PK", "SAR": "SA", "AED": "AE", "CNY": "CN",
    "NZD": "NZ", "ZAR": "ZA", "TRY": "TR", "BRL": "BR", "MXN": "MX",
}


@dataclass(slots=True)
class MacroPoint:
    country: str
    indicator: MacroIndicatorType
    year: int
    value: float


class WorldBankClient:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=True)
        return self._client

    def fetch(
        self,
        country: str,
        indicator: MacroIndicatorType,
        start_year: int,
        end_year: int,
    ) -> list[MacroPoint]:
        code = WB_CODES[indicator]
        url = f"{BASE_URL}/country/{country}/indicator/{code}"
        params = {"format": "json", "per_page": 200, "date": f"{start_year}:{end_year}"}
        try:
            resp = self._http().get(url, params=params)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            log.warning("World Bank fetch failed (%s/%s): %s", country, code, exc)
            return []

        # payload = [metadata, [records]] ; records may be missing/None.
        if not isinstance(payload, list) or len(payload) < 2 or not payload[1]:
            return []
        out: list[MacroPoint] = []
        for rec in payload[1]:
            value = rec.get("value")
            year_str = rec.get("date")
            if value is None or not year_str:
                continue
            try:
                out.append(
                    MacroPoint(country, indicator, int(year_str), float(value))
                )
            except (TypeError, ValueError):
                continue
        return out


def currencies_in_use(db: Session) -> set[str]:
    """Base+quote currencies from active forex securities (symbol like EURUSD)."""
    symbols = db.scalars(
        select(Security.symbol).where(
            Security.asset_class == AssetClass.FOREX, Security.is_active.is_(True)
        )
    ).all()
    currencies: set[str] = set()
    for sym in symbols:
        if len(sym) == 6:
            currencies.add(sym[:3])
            currencies.add(sym[3:])
    return currencies


def upsert_macro(db: Session, points: list[MacroPoint]) -> int:
    written = 0
    for p in points:
        period = date(p.year, 12, 31)
        row = db.scalar(
            select(MacroIndicator).where(
                MacroIndicator.country == p.country,
                MacroIndicator.indicator == p.indicator,
                MacroIndicator.period_date == period,
            )
        )
        if row is None:
            row = MacroIndicator(
                country=p.country, indicator=p.indicator, period_date=period
            )
            db.add(row)
        row.value = p.value
        row.source = "worldbank"
        written += 1
    return written


def ingest_macro(
    db: Session,
    client: WorldBankClient,
    currencies: set[str] | None = None,
    years: int = 8,
) -> dict[str, int]:
    """Fetch and store macro indicators for the countries behind our forex pairs."""
    currencies = currencies or currencies_in_use(db)
    countries = {CURRENCY_COUNTRY[c] for c in currencies if c in CURRENCY_COUNTRY}
    end_year = date.today().year
    start_year = end_year - years

    total = 0
    for country in sorted(countries):
        for indicator in WB_CODES:
            points = client.fetch(country, indicator, start_year, end_year)
            total += upsert_macro(db, points)
        db.commit()
    result = {"countries": len(countries), "points": total}
    log.info("ingest_macro: %s", result)
    return result
