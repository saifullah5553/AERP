"""Universal insider-transaction ingestion via Yahoo (``yfinance``).

Yahoo exposes recent insider transactions for most global equities it covers, so
this one source gives real insider activity for US, India, GCC, and Australia (PSX
is not covered by Yahoo — that stays on the PSX portal/CSV path). Rows feed the same
InsiderTransaction table and 60-day insider engine used by the SEC Form 4 path.

The fetcher is injectable so tests run without network or yfinance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.corporate import InsiderTransaction
from app.models.enums import AssetClass, InsiderTransactionType, MarketRegion
from app.models.market import Market, Security

log = get_logger(__name__)


@runtime_checkable
class InsiderFetcher(Protocol):
    def transactions(self, provider_symbol: str) -> list[dict[str, Any]]: ...


@dataclass(slots=True)
class InsiderRow:
    transaction_date: date
    insider_name: str | None
    title: str | None
    transaction_type: InsiderTransactionType
    shares: float | None
    price: float | None
    value: float | None


def _classify(text: str, transaction: str) -> InsiderTransactionType | None:
    """Map Yahoo's free-text description to our transaction type."""
    t = f"{text} {transaction}".lower()
    if any(w in t for w in ("purchase", "buy", "bought")):
        return InsiderTransactionType.BUY
    if any(w in t for w in ("sale", "sold", "sell", "disposition")):
        return InsiderTransactionType.SELL
    if any(w in t for w in ("option", "exercise", "conversion")):
        return InsiderTransactionType.EXERCISE
    if any(w in t for w in ("grant", "award", "gift", "acquisition")):
        return InsiderTransactionType.GRANT
    return None


def _price_from_text(text: str) -> float | None:
    m = re.search(r"price\s+([\d,]+\.?\d*)", text or "", re.IGNORECASE)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _num(v: Any) -> float | None:
    try:
        f = float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return None if f != f else f  # drop NaN


def parse_rows(raw: list[dict[str, Any]]) -> list[InsiderRow]:
    """Normalise yfinance insider_transactions records into InsiderRow."""
    out: list[InsiderRow] = []
    for r in raw:
        raw_date = r.get("Start Date") or r.get("startDate") or r.get("date")
        d: date | None = None
        if isinstance(raw_date, datetime):
            d = raw_date.date()
        elif isinstance(raw_date, date):
            d = raw_date
        elif isinstance(raw_date, str) and raw_date.strip():
            try:
                d = datetime.fromisoformat(raw_date.strip()[:19]).date()
            except ValueError:
                d = None
        if d is None:
            continue

        text = str(r.get("Text") or "")
        ttype = _classify(text, str(r.get("Transaction") or ""))
        if ttype is None:
            continue
        shares = _num(r.get("Shares"))
        value = _num(r.get("Value"))
        price = _price_from_text(text)
        if price is None and shares and value:
            price = value / shares
        out.append(InsiderRow(
            transaction_date=d,
            insider_name=(str(r.get("Insider")).strip() or None) if r.get("Insider") else None,
            title=(str(r.get("Position")).strip() or None) if r.get("Position") else None,
            transaction_type=ttype,
            shares=shares,
            price=price,
            value=value,
        ))
    return out


class YFinanceInsiderFetcher:
    """Real fetcher backed by yfinance (lazy import)."""

    def transactions(self, provider_symbol: str) -> list[dict[str, Any]]:
        import yfinance as yf

        df = yf.Ticker(provider_symbol).insider_transactions
        if df is None or getattr(df, "empty", True):
            return []
        return df.to_dict("records")


def ingest_for_security(db: Session, fetcher: InsiderFetcher, security: Security) -> int:
    """Insert new insider rows for one security (idempotent by date+name+shares)."""
    try:
        raw = fetcher.transactions(security.provider_symbol)
    except Exception as exc:  # pragma: no cover - network dependent
        log.warning("Yahoo insider failed for %s: %s", security.provider_symbol, exc)
        return 0
    rows = parse_rows(raw)
    if not rows:
        return 0

    existing = {
        (d, name, float(sh) if sh is not None else None)
        for d, name, sh in db.execute(
            select(
                InsiderTransaction.transaction_date,
                InsiderTransaction.insider_name,
                InsiderTransaction.shares,
            ).where(InsiderTransaction.security_id == security.id)
        ).all()
    }
    written = 0
    for r in rows:
        key = (r.transaction_date, r.insider_name, r.shares)
        if key in existing:
            continue
        existing.add(key)
        db.add(InsiderTransaction(
            security_id=security.id,
            transaction_date=r.transaction_date,
            insider_name=r.insider_name,
            insider_title=r.title,
            transaction_type=r.transaction_type,
            shares=r.shares,
            price=r.price,
            value=r.value,
        ))
        written += 1
    return written


def ingest_yahoo_insider(
    db: Session,
    fetcher: InsiderFetcher | None = None,
    region: MarketRegion | None = None,
    limit: int | None = None,
) -> dict[str, int]:
    """Ingest insider transactions for Yahoo-covered equities (optionally by region)."""
    fetcher = fetcher or YFinanceInsiderFetcher()
    stmt = (
        select(Security)
        .join(Market, Security.market_id == Market.id)
        .where(Security.asset_class == AssetClass.EQUITY, Security.is_active.is_(True))
    )
    if region is not None:
        stmt = stmt.where(Market.region == region)
    if limit is not None:
        stmt = stmt.limit(limit)

    secs = db.scalars(stmt).all()
    total = covered = 0
    for i, sec in enumerate(secs, 1):
        n = ingest_for_security(db, fetcher, sec)
        total += n
        covered += 1 if n else 0
        if i % 25 == 0:
            db.commit()
    db.commit()
    result = {"securities": len(secs), "with_transactions": covered, "written": total}
    log.info("ingest-yahoo-insider: %s", result)
    return result
