"""PSX provider — Pakistan Stock Exchange official data portal (keyless).

The portal at ``dps.psx.com.pk/all`` renders a full market table as HTML. We parse
it per-row (tolerant to attribute order/whitespace) rather than with one brittle
mega-regex, which was a weakness of the legacy scraper.

Only quotes and the universe are available from the portal; daily history is not,
so :meth:`get_daily` is intentionally unimplemented and the registry falls back.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from app.core.logging import get_logger
from app.ingestion.providers.base import (
    MarketDataProvider,
    QuoteDTO,
    SecurityProfile,
)
from app.models.enums import AssetClass, MarketRegion

log = get_logger(__name__)

ALL_URL = "https://dps.psx.com.pk/all"
SUFFIX = ".KA"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

_SYMBOL_RE = re.compile(r">\s*([A-Z0-9&]+)\s*</a>")
_CURRENT_RE = re.compile(r'class="current"[^>]*>\s*([\d,]+\.?\d*)')
_CHANGE_RE = re.compile(r'class="change"[^>]*>\s*(-?[\d,]+\.?\d*)')
_VOLUME_RE = re.compile(r'class="volume"[^>]*>\s*([\d,]+)')


def _num(text: str) -> float:
    return float(text.replace(",", "").strip())


def parse_psx_html(html: str) -> dict[str, QuoteDTO]:
    """Parse the PSX ``/all`` table into quotes keyed by ``SYMBOL.KA``."""
    out: dict[str, QuoteDTO] = {}
    now = datetime.now(UTC)
    # Split into row fragments; the first fragment is the pre-table header.
    for fragment in re.split(r"<tr[\s>]", html)[1:]:
        sym_m = _SYMBOL_RE.search(fragment)
        cur_m = _CURRENT_RE.search(fragment)
        if not sym_m or not cur_m:
            continue
        symbol = sym_m.group(1).strip().upper()
        try:
            price = _num(cur_m.group(1))
        except ValueError:
            continue
        change = None
        chg_m = _CHANGE_RE.search(fragment)
        if chg_m:
            try:
                change = _num(chg_m.group(1))
            except ValueError:
                change = None
        volume = None
        vol_m = _VOLUME_RE.search(fragment)
        if vol_m:
            try:
                volume = int(_num(vol_m.group(1)))
            except ValueError:
                volume = None

        prev_close = price - change if change is not None else None
        provider_symbol = f"{symbol}{SUFFIX}"
        out[provider_symbol] = QuoteDTO(
            provider_symbol=provider_symbol,
            price=price,
            prev_close=prev_close,
            change=change,
            volume=volume,
            quoted_at=now,
        ).filled()
    return out


class PSXProvider(MarketDataProvider):
    name = "psx"

    def supports(self, asset_class: AssetClass, region: MarketRegion) -> bool:
        return asset_class == AssetClass.EQUITY and region == MarketRegion.PSX

    def _fetch_all(self) -> dict[str, QuoteDTO]:
        try:
            resp = self._http().get(ALL_URL, headers=_HEADERS)
            resp.raise_for_status()
            return parse_psx_html(resp.text)
        except Exception as exc:
            log.warning("PSX portal fetch failed: %s", exc)
            return {}

    def get_quotes(self, provider_symbols: list[str]) -> dict[str, QuoteDTO]:
        if not provider_symbols:
            return {}
        wanted = set(provider_symbols)
        allq = self._fetch_all()
        return {sym: q for sym, q in allq.items() if sym in wanted}

    def list_universe(self) -> list[SecurityProfile]:
        allq = self._fetch_all()
        return [
            SecurityProfile(
                symbol=sym[: -len(SUFFIX)],
                name=None,
                asset_class=AssetClass.EQUITY,
                exchange="PSX",
                currency="PKR",
                country="PK",
            )
            for sym in allq
        ]
