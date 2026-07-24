"""Twelve Data provider — requires an API key.

Primary source for forex and commodities; best-effort fallback for India/GCC
equities (coverage is thin on the free tier — an honest limitation, documented in
docs/ROADMAP.md). The free tier does not batch quotes, so quotes are fetched per
symbol; the pipeline bounds how many symbols are requested per cycle.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.core.config import settings
from app.core.logging import get_logger
from app.ingestion.providers.base import (
    MarketDataProvider,
    OHLCVBar,
    QuoteDTO,
)
from app.models.enums import AssetClass, MarketRegion

log = get_logger(__name__)

BASE_URL = "https://api.twelvedata.com"

# A few reliable commodity mappings; anything else is a known gap.
COMMODITY_MAP = {"GC": "XAU/USD", "SI": "XAG/USD", "PL": "XPT/USD"}
# Suffix → Twelve Data exchange hint for equities.
EXCHANGE_BY_SUFFIX = {".NS": "NSE", ".BO": "BSE", ".SR": "Tadawul"}


def _map_symbol(provider_symbol: str) -> tuple[str, str | None]:
    """Return (twelve_data_symbol, exchange_hint)."""
    if provider_symbol.endswith("=X"):
        base = provider_symbol[:-2]
        if len(base) == 6:  # e.g. EURUSD -> EUR/USD
            return f"{base[:3]}/{base[3:]}", None
        return base, None
    if provider_symbol.endswith("=F"):
        base = provider_symbol[:-2]
        return COMMODITY_MAP.get(base, base), None
    for suffix, exch in EXCHANGE_BY_SUFFIX.items():
        if provider_symbol.endswith(suffix):
            return provider_symbol[: -len(suffix)], exch
    return provider_symbol, None


class TwelveDataProvider(MarketDataProvider):
    name = "twelvedata"

    @property
    def available(self) -> bool:
        return bool(settings.twelve_data_api_key)

    def supports(self, asset_class: AssetClass, region: MarketRegion) -> bool:
        if asset_class in {AssetClass.FOREX, AssetClass.COMMODITY, AssetClass.INDEX}:
            return True
        # Equity fallback for non-US, non-PSX markets.
        return asset_class == AssetClass.EQUITY and region in {
            MarketRegion.INDIA,
            MarketRegion.GCC,
            MarketRegion.US,
        }

    def _params(self, extra: dict) -> dict:
        return {"apikey": settings.twelve_data_api_key, **extra}

    def get_quotes(self, provider_symbols: list[str]) -> dict[str, QuoteDTO]:
        if not self.available:
            return {}
        out: dict[str, QuoteDTO] = {}
        for provider_symbol in provider_symbols:
            td_symbol, exchange = _map_symbol(provider_symbol)
            extra = {"symbol": td_symbol}
            if exchange:
                extra["exchange"] = exchange
            try:
                resp = self._http().get(f"{BASE_URL}/quote", params=self._params(extra))
                resp.raise_for_status()
                row = resp.json()
            except Exception as exc:
                log.warning("TwelveData quote failed for %s: %s", provider_symbol, exc)
                continue
            if not isinstance(row, dict) or row.get("status") == "error" or "close" not in row:
                continue
            try:
                out[provider_symbol] = QuoteDTO(
                    provider_symbol=provider_symbol,
                    price=float(row["close"]),
                    prev_close=_f(row.get("previous_close")),
                    change=_f(row.get("change")),
                    change_pct=_f(row.get("percent_change")),
                    day_open=_f(row.get("open")),
                    day_high=_f(row.get("high")),
                    day_low=_f(row.get("low")),
                    volume=_i(row.get("volume")),
                    quoted_at=datetime.now(UTC),
                ).filled()
            except (KeyError, TypeError, ValueError):
                continue
        return out

    def get_daily(self, provider_symbol: str, start: date | None = None) -> list[OHLCVBar]:
        if not self.available:
            return []
        td_symbol, exchange = _map_symbol(provider_symbol)
        extra = {"symbol": td_symbol, "interval": "1day", "outputsize": 5000}
        if exchange:
            extra["exchange"] = exchange
        if start:
            extra["start_date"] = start.isoformat()
        try:
            resp = self._http().get(f"{BASE_URL}/time_series", params=self._params(extra))
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.warning("TwelveData time_series failed for %s: %s", provider_symbol, exc)
            return []
        if not isinstance(data, dict) or data.get("status") == "error":
            return []

        bars: list[OHLCVBar] = []
        for row in reversed(data.get("values", [])):  # newest-first from API
            try:
                bars.append(
                    OHLCVBar(
                        date=date.fromisoformat(row["datetime"][:10]),
                        open=_f(row.get("open")),
                        high=_f(row.get("high")),
                        low=_f(row.get("low")),
                        close=float(row["close"]),
                        adj_close=_f(row.get("close")),
                        volume=_i(row.get("volume")),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return bars


def _f(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _i(value) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None
