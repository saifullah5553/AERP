"""Provider abstraction.

Every data source implements :class:`MarketDataProvider`. The rest of the system
depends only on this interface and the plain DTOs below, so swapping or adding a
provider (e.g. a paid EODHD) never touches the engines, tasks, or API.

Design rules:
- Providers translate the platform's ``provider_symbol`` to their own symbol
  format internally (e.g. ``BTC-USD`` → ``BTCUSDT`` for Binance).
- Providers never fabricate. On error or missing data they omit the symbol from
  the result; they never invent a price.
- Network access goes through an injectable ``httpx.Client`` so tests drive them
  with a mock transport and no real network.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import httpx

from app.models.enums import AssetClass, MarketRegion, StatementPeriod

DEFAULT_TIMEOUT = httpx.Timeout(15.0, connect=8.0)


@dataclass(slots=True)
class QuoteDTO:
    """A latest-price snapshot for one instrument."""

    provider_symbol: str
    price: float
    prev_close: float | None = None
    change: float | None = None
    change_pct: float | None = None
    day_open: float | None = None
    day_high: float | None = None
    day_low: float | None = None
    volume: int | None = None
    quoted_at: datetime | None = None

    def filled(self) -> QuoteDTO:
        """Derive change/change_pct from price and prev_close when absent."""
        if self.change is None and self.prev_close is not None:
            self.change = self.price - self.prev_close
        if (
            self.change_pct is None
            and self.prev_close not in (None, 0)
            and self.change is not None
        ):
            self.change_pct = self.change / self.prev_close * 100
        return self


@dataclass(slots=True)
class OHLCVBar:
    """One daily OHLCV bar."""

    date: date
    open: float | None
    high: float | None
    low: float | None
    close: float
    adj_close: float | None = None
    volume: int | None = None


@dataclass(slots=True)
class SecurityProfile:
    """A universe entry discovered from a provider's symbol directory."""

    symbol: str            # exchange-local symbol
    name: str | None
    asset_class: AssetClass
    # Market code this symbol belongs to (e.g. "NASDAQ", "PSX", "CRYPTO"), used by
    # the universe loader to attach the security to the correct market.
    exchange: str | None = None
    sector: str | None = None
    industry: str | None = None
    currency: str | None = None
    country: str | None = None
    market_cap: float | None = None


@dataclass(slots=True)
class StatementDTO:
    """One financial statement, decoupled from the ORM.

    ``statement_type`` is one of ``income`` / ``balance`` / ``cashflow``.
    ``values`` maps ORM column names to values, so the repository can persist any
    statement type generically.
    """

    statement_type: str
    fiscal_date: date
    period: StatementPeriod
    reported_currency: str | None = None
    values: dict[str, Any] = field(default_factory=dict)


class ProviderUnavailable(RuntimeError):
    """Raised when a provider cannot run (e.g. missing API key)."""


class MarketDataProvider(ABC):
    """Interface every data source implements."""

    #: Stable, lower-case identifier used in logs and the fallback chain.
    name: str = "base"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client

    # ── Capabilities ─────────────────────────────────────────
    @abstractmethod
    def supports(self, asset_class: AssetClass, region: MarketRegion) -> bool:
        """Whether this provider can serve the given security kind."""

    @property
    def available(self) -> bool:
        """Whether the provider is usable right now (keys present, etc.)."""
        return True

    # ── Data access (override what the source offers) ─────────
    def get_quotes(self, provider_symbols: list[str]) -> dict[str, QuoteDTO]:
        """Return quotes keyed by ``provider_symbol``. Missing symbols omitted."""
        raise NotImplementedError

    def get_daily(self, provider_symbol: str, start: date | None = None) -> list[OHLCVBar]:
        """Return daily OHLCV bars ascending by date."""
        raise NotImplementedError

    def list_universe(self) -> list[SecurityProfile]:
        """Return the provider's symbol directory, if it exposes one."""
        raise NotImplementedError

    def get_statements(
        self, provider_symbol: str, period: StatementPeriod, limit: int = 5
    ) -> list[StatementDTO]:
        """Return income/balance/cash-flow statements for a security."""
        raise NotImplementedError

    # ── Helpers ──────────────────────────────────────────────
    def _http(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        self._client = httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=True)
        return self._client
