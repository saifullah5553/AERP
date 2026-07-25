"""Comprehensive PSX insider transactions from the Portfolio360 backend API.

Portfolio360 (portfolio360.app) aggregates PSX director/insider dealings disclosed
to the exchange and serves them as JSON from ``backend.capitalmarketsforall.com``.
This replaces the tiny committed CSV sample with the full recent window (hundreds of
real filings), feeding the same InsiderTransaction table + 60-day insider engine.

The endpoint is CORS-gated, so the browser Origin/Referer headers are required. The
client is injectable so tests run offline.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.corporate import InsiderTransaction
from app.models.enums import InsiderTransactionType
from app.models.market import Market, Security

log = get_logger(__name__)

API_URL = "https://backend.capitalmarketsforall.com/api/market/insider-transactions"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AERP/1.0)",
    "Origin": "https://portfolio360.app",
    "Referer": "https://portfolio360.app/",
    "Accept": "application/json",
}


class PSXInsiderAPIClient:
    """Fetches the Portfolio360 insider feed. Inject a client with a MockTransport
    in tests to avoid network access."""

    def __init__(self, client: httpx.Client | None = None, timeout: float = 40.0):
        self._client = client or httpx.Client(headers=_HEADERS, timeout=timeout)

    def fetch(self, limit: int = 500) -> list[dict[str, Any]]:
        resp = self._client.get(API_URL, params={"limit": limit})
        resp.raise_for_status()
        try:
            payload = resp.json()
        except json.JSONDecodeError:
            return []
        return payload.get("items", []) if isinstance(payload, dict) else []


@dataclass(slots=True)
class ParsedInsider:
    symbol: str
    transaction_date: date
    person: str | None
    role: str | None
    transaction_type: InsiderTransactionType
    shares: float | None
    price: float | None
    value: float | None


_NATURE = {
    "BUY": InsiderTransactionType.BUY,
    "PURCHASE": InsiderTransactionType.BUY,
    "SELL": InsiderTransactionType.SELL,
    "SALE": InsiderTransactionType.SELL,
}


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def _date(v: Any) -> date | None:
    if isinstance(v, str) and v.strip():
        try:
            return datetime.fromisoformat(v.strip()[:10]).date()
        except ValueError:
            return None
    return None


def parse_items(items: list[dict[str, Any]]) -> list[ParsedInsider]:
    out: list[ParsedInsider] = []
    for it in items:
        sym = (it.get("symbol") or "").strip().upper()
        d = _date(it.get("date") or it.get("announcedAt"))
        ttype = _NATURE.get(str(it.get("nature") or "").strip().upper())
        if not sym or d is None or ttype is None:
            continue
        out.append(ParsedInsider(
            symbol=sym,
            transaction_date=d,
            person=(str(it.get("person")).strip() or None) if it.get("person") else None,
            role=(str(it.get("role")).strip() or None) if it.get("role") else None,
            transaction_type=ttype,
            shares=_num(it.get("shares")),
            price=_num(it.get("rate")),
            value=_num(it.get("value")),
        ))
    return out


def ingest_psx_insider_api(
    db: Session, client: PSXInsiderAPIClient | None = None, limit: int = 500
) -> dict[str, int]:
    """Fetch and upsert PSX insider transactions for securities in our universe."""
    client = client or PSXInsiderAPIClient()
    psx = db.scalar(select(Market).where(Market.code == "PSX"))
    if psx is None:
        return {"fetched": 0, "written": 0, "unmatched": 0}
    by_symbol = {
        s.symbol: s for s in db.scalars(select(Security).where(Security.market_id == psx.id))
    }

    rows = parse_items(client.fetch(limit=limit))
    written = unmatched = 0
    seen_existing: dict[int, set] = {}
    for r in rows:
        sec = by_symbol.get(r.symbol)
        if sec is None:
            unmatched += 1
            continue
        if sec.id not in seen_existing:
            seen_existing[sec.id] = {
                (d, name, float(sh) if sh is not None else None)
                for d, name, sh in db.execute(
                    select(
                        InsiderTransaction.transaction_date,
                        InsiderTransaction.insider_name,
                        InsiderTransaction.shares,
                    ).where(InsiderTransaction.security_id == sec.id)
                ).all()
            }
        key = (r.transaction_date, r.person, r.shares)
        if key in seen_existing[sec.id]:
            continue
        seen_existing[sec.id].add(key)
        db.add(InsiderTransaction(
            security_id=sec.id,
            transaction_date=r.transaction_date,
            insider_name=r.person,
            insider_title=r.role,
            transaction_type=r.transaction_type,
            shares=r.shares,
            price=r.price,
            value=r.value,
        ))
        written += 1
    db.commit()
    result = {"fetched": len(rows), "written": written, "unmatched": unmatched}
    log.info("ingest-psx-insider-api: %s", result)
    return result
