"""PSX live market data from the official public portal (dps.psx.com.pk).

Free, keyless, and hosted in Pakistan — so it works from CI/datacenter IPs where
Yahoo returns HTTP 429. Three endpoints together fill everything the fundamentals-
only snapshot was missing for PSX:

* ``/symbols``            → company name + sector for every listed symbol (JSON)
* ``/market-watch``       → live OHLC + change + volume for the whole market (HTML)
* ``/timeseries/eod/SYM`` → daily close/volume history → feeds the technical engine

Parsers are pure functions (testable with canned payloads); the client is injectable
so tests never hit the network. As everywhere in AERP: only real values are written —
a missing/blank field stays ``None``, never a guess.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.enums import AssetClass
from app.models.market import Market, Security
from app.models.prices import DailyPrice
from app.models.quote import Quote

log = get_logger(__name__)

BASE_URL = "https://dps.psx.com.pk"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AERP/1.0)"}


# --------------------------------------------------------------------------- #
# HTTP client (injectable)
# --------------------------------------------------------------------------- #
class PSXPortalClient:
    """Thin wrapper over the dps.psx.com.pk endpoints. Inject a client with a
    ``httpx.MockTransport`` in tests to run without network access."""

    def __init__(self, client: httpx.Client | None = None, timeout: float = 25.0):
        self._client = client or httpx.Client(
            base_url=BASE_URL, headers=_HEADERS, timeout=timeout, follow_redirects=True
        )

    def symbols(self) -> str:
        return self._client.get("/symbols").text

    def market_watch(self) -> str:
        return self._client.get("/market-watch").text

    def eod(self, symbol: str) -> str:
        return self._client.get(f"/timeseries/eod/{symbol}").text


# --------------------------------------------------------------------------- #
# Pure parsers
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class SymbolMeta:
    symbol: str
    name: str | None
    sector: str | None
    is_etf: bool
    is_debt: bool


def parse_symbols(text: str) -> dict[str, SymbolMeta]:
    """``/symbols`` JSON → {symbol: SymbolMeta}."""
    out: dict[str, SymbolMeta] = {}
    try:
        rows = json.loads(text)
    except json.JSONDecodeError:
        return out
    for r in rows:
        sym = (r.get("symbol") or "").strip()
        if not sym:
            continue
        out[sym] = SymbolMeta(
            symbol=sym,
            name=(r.get("name") or "").strip() or None,
            sector=(r.get("sectorName") or "").strip() or None,
            is_etf=bool(r.get("isETF")),
            is_debt=bool(r.get("isDebt")),
        )
    return out


@dataclass(slots=True)
class MarketRow:
    symbol: str
    ldcp: float | None
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    change: float | None
    change_pct: float | None
    volume: int | None


def _num(text: str) -> float | None:
    t = (text or "").replace(",", "").replace("%", "").strip()
    if not t or t in {"-", "--"}:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def parse_market_watch(html: str) -> list[MarketRow]:
    """``/market-watch`` HTML table → one MarketRow per traded symbol.

    Columns (in order): symbol, sector, listed, ldcp, open, high, low, close,
    change, percentChange, volume.
    """
    body = re.search(r"<tbody.*?>(.*?)</tbody>", html, re.DOTALL)
    scope = body.group(1) if body else html
    rows: list[MarketRow] = []
    for tr in re.findall(r"<tr.*?>(.*?)</tr>", scope, re.DOTALL):
        cells = [
            re.sub(r"<[^>]+>", "", c).strip()
            for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.DOTALL)
        ]
        if len(cells) < 11:
            continue
        symbol = cells[0].strip()
        if not symbol:
            continue
        vol = _num(cells[10])
        rows.append(
            MarketRow(
                symbol=symbol,
                ldcp=_num(cells[3]),
                open=_num(cells[4]),
                high=_num(cells[5]),
                low=_num(cells[6]),
                close=_num(cells[7]),
                change=_num(cells[8]),
                change_pct=_num(cells[9]),
                volume=int(vol) if vol is not None else None,
            )
        )
    return rows


@dataclass(slots=True)
class EodBar:
    date: datetime  # tz-aware UTC
    close: float
    volume: int | None


def parse_eod(text: str) -> list[EodBar]:
    """``/timeseries/eod/SYM`` JSON → chronological EOD bars.

    Each tuple is ``[unix_ts, adjusted_close, volume, raw_close]``. We keep the
    split-adjusted close (index 1) so indicators are continuous across splits.
    """
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    data = payload.get("data") if isinstance(payload, dict) else None
    if not data:
        return []
    bars: list[EodBar] = []
    for row in data:
        if not row or len(row) < 2:
            continue
        try:
            ts = int(row[0])
            close = float(row[1])
        except (TypeError, ValueError):
            continue
        vol = None
        if len(row) >= 3 and row[2] is not None:
            try:
                vol = int(row[2])
            except (TypeError, ValueError):
                vol = None
        bars.append(EodBar(datetime.fromtimestamp(ts, tz=UTC), close, vol))
    bars.sort(key=lambda b: b.date)
    return bars


# --------------------------------------------------------------------------- #
# Ingestion
# --------------------------------------------------------------------------- #
def _psx_securities(db: Session) -> dict[str, Security]:
    """Existing PSX securities keyed by bare ticker (provider_symbol drops .KA)."""
    psx = db.scalar(select(Market).where(Market.code == "PSX"))
    if psx is None:
        return {}
    secs = db.scalars(select(Security).where(Security.market_id == psx.id)).all()
    return {s.symbol: s for s in secs}


def update_symbol_meta(db: Session, meta: dict[str, SymbolMeta]) -> int:
    """Fill name/sector on existing PSX securities from ``/symbols``."""
    secs = _psx_securities(db)
    updated = 0
    for sym, sec in secs.items():
        m = meta.get(sym)
        if m is None:
            continue
        changed = False
        if m.name and sec.name != m.name:
            sec.name = m.name
            changed = True
        if m.sector and sec.sector != m.sector:
            sec.sector = m.sector
            changed = True
        if changed:
            updated += 1
    if updated:
        db.commit()
    return updated


def ingest_quotes(db: Session, rows: list[MarketRow]) -> int:
    """Upsert the live Quote snapshot + today's DailyPrice bar from market-watch."""
    secs = _psx_securities(db)
    now = datetime.now(tz=UTC)
    today = now.date()
    n = 0
    for row in rows:
        sec = secs.get(row.symbol)
        if sec is None:
            continue
        price = row.close if row.close is not None else row.ldcp
        if price is None:
            continue

        quote = db.get(Quote, sec.id)
        if quote is None:
            quote = Quote(security_id=sec.id)
            db.add(quote)
        quote.price = price
        quote.prev_close = row.ldcp
        quote.change = row.change
        quote.change_pct = row.change_pct
        quote.day_open = row.open
        quote.day_high = row.high
        quote.day_low = row.low
        quote.volume = row.volume
        quote.quoted_at = now

        # Today's OHLC bar (real OHLC, unlike the close-only history).
        bar = db.scalar(
            select(DailyPrice).where(
                DailyPrice.security_id == sec.id, DailyPrice.date == today
            )
        )
        if bar is None:
            bar = DailyPrice(security_id=sec.id, date=today, close=price)
            db.add(bar)
        bar.open = row.open
        bar.high = row.high
        bar.low = row.low
        bar.close = price
        bar.volume = row.volume
        n += 1
    db.commit()
    return n


def ingest_history(
    db: Session, client: PSXPortalClient, symbols: list[str] | None = None, limit: int | None = None
) -> dict[str, int]:
    """Backfill DailyPrice history from the EOD endpoint so technicals can compute."""
    secs = _psx_securities(db)
    targets = symbols or list(secs.keys())
    if limit is not None:
        targets = targets[:limit]

    done = bars_written = failed = 0
    for sym in targets:
        sec = secs.get(sym)
        if sec is None:
            continue
        try:
            bars = parse_eod(client.eod(sym))
        except httpx.HTTPError:
            failed += 1
            continue
        if not bars:
            continue

        existing = {
            d
            for (d,) in db.execute(
                select(DailyPrice.date).where(DailyPrice.security_id == sec.id)
            ).all()
        }
        for b in bars:
            d = b.date.date()
            if d in existing:
                continue
            db.add(
                DailyPrice(
                    security_id=sec.id,
                    date=d,
                    close=b.close,
                    adj_close=b.close,
                    volume=b.volume,
                )
            )
            bars_written += 1
        done += 1
        # Commit periodically to keep the transaction small on large universes.
        if done % 25 == 0:
            db.commit()
    db.commit()
    return {"symbols": done, "bars": bars_written, "failed": failed}


def ingest_psx_market(
    db: Session,
    client: PSXPortalClient | None = None,
    with_history: bool = True,
    history_limit: int | None = None,
) -> dict[str, int]:
    """One-shot: names/sectors + live quotes + (optionally) price history."""
    client = client or PSXPortalClient()
    meta = parse_symbols(client.symbols())
    named = update_symbol_meta(db, meta)

    rows = parse_market_watch(client.market_watch())
    quoted = ingest_quotes(db, rows)

    result = {"named": named, "quoted": quoted}
    if with_history:
        result.update(ingest_history(db, client, limit=history_limit))
    log.info("ingest-psx-market: %s", result)
    return result


# Optionally create securities for symbols we have market data for but no
# fundamentals (kept off by default so the screener stays fundamentals-anchored).
def ensure_securities(db: Session, meta: dict[str, SymbolMeta]) -> int:
    psx = db.scalar(select(Market).where(Market.code == "PSX"))
    if psx is None:
        return 0
    have = _psx_securities(db)
    created = 0
    for sym, m in meta.items():
        if sym in have or m.is_debt or m.is_etf:
            continue
        db.add(
            Security(
                market_id=psx.id,
                symbol=sym,
                provider_symbol=f"{sym}.KA",
                name=m.name,
                sector=m.sector,
                asset_class=AssetClass.EQUITY,
                currency="PKR",
                country="PK",
                is_active=True,
            )
        )
        created += 1
    if created:
        db.commit()
    return created
