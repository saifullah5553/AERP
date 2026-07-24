"""Binance provider — crypto spot. Keyless public REST API.

Platform crypto symbols look like ``BTC-USD``; Binance uses ``BTCUSDT`` (USDT is
the liquid USD proxy). Mapping happens here and nowhere else.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

from app.core.logging import get_logger
from app.ingestion.providers.base import (
    MarketDataProvider,
    OHLCVBar,
    QuoteDTO,
    SecurityProfile,
)
from app.models.enums import AssetClass, MarketRegion

log = get_logger(__name__)

BASE_URL = "https://api.binance.com"
QUOTE_ASSET = "USDT"


def _to_binance(provider_symbol: str) -> str:
    # "BTC-USD" -> "BTCUSDT"
    base = provider_symbol.replace("-USD", "").replace("-USDT", "")
    return f"{base}{QUOTE_ASSET}"


def _to_provider(binance_symbol: str) -> str:
    # "BTCUSDT" -> "BTC-USD"
    if binance_symbol.endswith(QUOTE_ASSET):
        base = binance_symbol[: -len(QUOTE_ASSET)]
    else:
        base = binance_symbol
    return f"{base}-USD"


class BinanceProvider(MarketDataProvider):
    name = "binance"

    def supports(self, asset_class: AssetClass, region: MarketRegion) -> bool:
        return asset_class == AssetClass.CRYPTO

    def get_quotes(self, provider_symbols: list[str]) -> dict[str, QuoteDTO]:
        if not provider_symbols:
            return {}
        mapping = {_to_binance(s): s for s in provider_symbols}
        symbols_param = json.dumps(list(mapping.keys()))
        try:
            resp = self._http().get(
                f"{BASE_URL}/api/v3/ticker/24hr", params={"symbols": symbols_param}
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            log.warning("Binance quotes failed: %s", exc)
            return {}

        out: dict[str, QuoteDTO] = {}
        now = datetime.now(UTC)
        for row in payload:
            bsym = row.get("symbol")
            provider_symbol = mapping.get(bsym)
            if provider_symbol is None:
                continue
            try:
                last = float(row["lastPrice"])
                prev = float(row.get("prevClosePrice") or 0) or None
                out[provider_symbol] = QuoteDTO(
                    provider_symbol=provider_symbol,
                    price=last,
                    prev_close=prev,
                    change=float(row.get("priceChange") or 0),
                    change_pct=float(row.get("priceChangePercent") or 0),
                    day_open=_f(row.get("openPrice")),
                    day_high=_f(row.get("highPrice")),
                    day_low=_f(row.get("lowPrice")),
                    volume=int(float(row.get("volume") or 0)),
                    quoted_at=now,
                )
            except (KeyError, TypeError, ValueError):
                continue
        return out

    def get_daily(self, provider_symbol: str, start: date | None = None) -> list[OHLCVBar]:
        bsym = _to_binance(provider_symbol)
        params = {"symbol": bsym, "interval": "1d", "limit": 1000}
        if start is not None:
            params["startTime"] = int(
                datetime(start.year, start.month, start.day, tzinfo=UTC).timestamp() * 1000
            )
        try:
            resp = self._http().get(f"{BASE_URL}/api/v3/klines", params=params)
            resp.raise_for_status()
            rows = resp.json()
        except Exception as exc:
            log.warning("Binance klines failed for %s: %s", provider_symbol, exc)
            return []

        bars: list[OHLCVBar] = []
        for k in rows:
            # [openTime, open, high, low, close, volume, closeTime, ...]
            try:
                bar_date = datetime.fromtimestamp(k[0] / 1000, tz=UTC).date()
                bars.append(
                    OHLCVBar(
                        date=bar_date,
                        open=float(k[1]),
                        high=float(k[2]),
                        low=float(k[3]),
                        close=float(k[4]),
                        adj_close=float(k[4]),
                        volume=int(float(k[5])),
                    )
                )
            except (IndexError, TypeError, ValueError):
                continue
        return bars

    def list_universe(self) -> list[SecurityProfile]:
        try:
            resp = self._http().get(f"{BASE_URL}/api/v3/exchangeInfo")
            resp.raise_for_status()
            info = resp.json()
        except Exception as exc:
            log.warning("Binance exchangeInfo failed: %s", exc)
            return []

        profiles: list[SecurityProfile] = []
        seen: set[str] = set()
        for s in info.get("symbols", []):
            if s.get("status") != "TRADING" or s.get("quoteAsset") != QUOTE_ASSET:
                continue
            base = s.get("baseAsset")
            if not base or base in seen:
                continue
            seen.add(base)
            profiles.append(
                SecurityProfile(
                    symbol=base,
                    name=base,
                    asset_class=AssetClass.CRYPTO,
                    exchange="CRYPTO",
                    currency="USD",
                )
            )
        return profiles


def _f(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
