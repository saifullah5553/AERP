"""Provider registry and fallback routing.

Given a security's ``(asset_class, region)`` this decides which providers to try
and in what order, then resolves quotes/history through that chain — the first
provider to return data wins, the rest are fallbacks. Adding a paid provider is a
one-line change to :data:`ROUTING` plus registering its instance.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

import httpx

from app.core.logging import get_logger
from app.ingestion.providers.base import (
    MarketDataProvider,
    OHLCVBar,
    QuoteDTO,
    SecurityProfile,
)
from app.ingestion.providers.binance import BinanceProvider
from app.ingestion.providers.fmp import FMPProvider
from app.ingestion.providers.psx import PSXProvider
from app.ingestion.providers.twelvedata import TwelveDataProvider
from app.models.enums import AssetClass, MarketRegion

log = get_logger(__name__)

# Ordered provider names per routing key. Key is asset_class, except equities are
# further keyed by region because coverage differs sharply by market.
ROUTING: dict[object, list[str]] = {
    AssetClass.CRYPTO: ["binance"],
    AssetClass.FOREX: ["twelvedata", "fmp"],
    AssetClass.COMMODITY: ["twelvedata", "fmp"],
    AssetClass.INDEX: ["twelvedata", "fmp"],
    AssetClass.ETF: ["fmp", "twelvedata"],
    (AssetClass.EQUITY, MarketRegion.US): ["fmp", "twelvedata"],
    (AssetClass.EQUITY, MarketRegion.PSX): ["psx"],
    (AssetClass.EQUITY, MarketRegion.INDIA): ["twelvedata", "fmp"],
    (AssetClass.EQUITY, MarketRegion.GCC): ["twelvedata", "fmp"],
    (AssetClass.EQUITY, MarketRegion.GLOBAL): ["fmp", "twelvedata"],
}


@dataclass(slots=True)
class SecurityRef:
    """The minimum a caller needs to route a security."""

    provider_symbol: str
    asset_class: AssetClass
    region: MarketRegion


class ProviderRegistry:
    def __init__(self, client: httpx.Client | None = None) -> None:
        # A shared client is optional; tests inject a mock-transport client.
        self._providers: dict[str, MarketDataProvider] = {
            "binance": BinanceProvider(client),
            "psx": PSXProvider(client),
            "fmp": FMPProvider(client),
            "twelvedata": TwelveDataProvider(client),
        }

    def provider(self, name: str) -> MarketDataProvider | None:
        return self._providers.get(name)

    def order_for(self, asset_class: AssetClass, region: MarketRegion) -> list[str]:
        if asset_class == AssetClass.EQUITY:
            return ROUTING.get((asset_class, region), ["fmp", "twelvedata"])
        return ROUTING.get(asset_class, [])

    # ── Quotes ───────────────────────────────────────────────
    def get_quotes(self, refs: list[SecurityRef]) -> dict[str, QuoteDTO]:
        # Group symbols that share an identical provider chain so each provider is
        # called with a batch rather than one symbol at a time.
        groups: dict[tuple[str, ...], list[str]] = defaultdict(list)
        for ref in refs:
            order = tuple(self.order_for(ref.asset_class, ref.region))
            if order:
                groups[order].append(ref.provider_symbol)

        results: dict[str, QuoteDTO] = {}
        for order, symbols in groups.items():
            remaining = set(symbols)
            for name in order:
                if not remaining:
                    break
                provider = self._providers.get(name)
                if provider is None or not provider.available:
                    continue
                try:
                    got = provider.get_quotes(list(remaining))
                except Exception as exc:  # pragma: no cover - defensive
                    log.warning("Provider %s get_quotes raised: %s", name, exc)
                    continue
                for sym, quote in got.items():
                    results[sym] = quote
                    remaining.discard(sym)
        return results

    # ── Daily history ────────────────────────────────────────
    def get_daily(self, ref: SecurityRef, start: date | None = None) -> list[OHLCVBar]:
        for name in self.order_for(ref.asset_class, ref.region):
            provider = self._providers.get(name)
            if provider is None or not provider.available:
                continue
            try:
                bars = provider.get_daily(ref.provider_symbol, start)
            except NotImplementedError:
                continue
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("Provider %s get_daily raised: %s", name, exc)
                continue
            if bars:
                return bars
        return []

    # ── Universe discovery ───────────────────────────────────
    def discover_universe(self, provider_names: list[str] | None = None) -> list[SecurityProfile]:
        names = provider_names or list(self._providers.keys())
        profiles: list[SecurityProfile] = []
        for name in names:
            provider = self._providers.get(name)
            if provider is None or not provider.available:
                continue
            try:
                found = provider.list_universe()
            except NotImplementedError:
                continue
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("Provider %s list_universe raised: %s", name, exc)
                continue
            log.info("Universe: %s contributed %d symbols", name, len(found))
            profiles.extend(found)
        return profiles
