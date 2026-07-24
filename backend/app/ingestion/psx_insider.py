"""PSX insider/director transactions from a CSV (Sarmaaya / PSX / ksestocks).

PSX insider data has no clean public API — it's scraped (see
``scripts/scrape_psx_insider.py``) into a CSV, which this module loads into the
same ``insider_transactions`` table the market-agnostic insider engine already
scores (60-day buy/sell signal). Header matching is deliberately flexible so it
works across the slightly different exports these sites produce.

Expected-ish columns (any casing / common synonyms accepted):
    symbol, insider, title, date, type (buy/sell), shares, price[, value]
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.corporate import InsiderTransaction
from app.models.enums import AssetClass, InsiderTransactionType
from app.models.market import Market, Security

log = get_logger(__name__)

# Our field → accepted header synonyms (lowercased, substring match).
FIELD_SYNONYMS: dict[str, list[str]] = {
    "symbol": ["symbol", "scrip", "company", "code", "ticker"],
    "insider": ["insider", "name", "director", "person", "holder", "sponsor"],
    "title": ["title", "designation", "relation", "capacity", "category"],
    "date": ["date", "dealing date", "transaction date"],
    "type": ["type", "nature", "buy/sell", "transaction", "mode", "action"],
    "shares": ["shares", "quantity", "volume", "qty", "no. of shares", "no of shares"],
    "price": ["price", "rate", "value per share", "avg rate", "average rate"],
    "value": ["value", "amount", "total", "consideration"],
}

_DATE_FORMATS = [
    "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%b %d, %Y", "%d-%b-%Y", "%d %b %Y",
]


def _match_columns(header: list[str]) -> dict[str, int]:
    """Map our field names to column indices using synonym substring matching."""
    lowered = [h.strip().lower() for h in header]
    out: dict[str, int] = {}
    for field, syns in FIELD_SYNONYMS.items():
        for i, col in enumerate(lowered):
            if any(s in col for s in syns):
                out[field] = i
                break
    return out


def _num(text: str | None) -> float | None:
    if not text:
        return None
    t = text.strip().replace(",", "")
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()")
    if not t or t in {"-", "—"}:
        return None
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def _parse_date(text: str | None) -> date | None:
    if not text:
        return None
    t = text.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    return None


def _parse_type(text: str | None) -> InsiderTransactionType | None:
    if not text:
        return None
    t = text.strip().lower()
    if any(k in t for k in ("buy", "purchas", "acqui", "bought")):
        return InsiderTransactionType.BUY
    if any(k in t for k in ("sell", "sold", "dispos", "sale")):
        return InsiderTransactionType.SELL
    return None


@dataclass(slots=True)
class InsiderRow:
    symbol: str
    insider: str | None
    title: str | None
    transaction_date: date
    transaction_type: InsiderTransactionType
    shares: float | None
    price: float | None
    value: float | None


def parse_insider_csv(text: str) -> list[InsiderRow]:
    rows_in = [r for r in csv.reader(io.StringIO(text)) if r]
    if not rows_in:
        return []
    cols = _match_columns(rows_in[0])
    if "symbol" not in cols or "date" not in cols or "type" not in cols:
        log.warning("PSX insider CSV missing required columns; got %s", list(cols))
        return []

    def get(row: list[str], field: str) -> str | None:
        idx = cols.get(field)
        return row[idx].strip() if idx is not None and idx < len(row) else None

    out: list[InsiderRow] = []
    for row in rows_in[1:]:
        symbol = (get(row, "symbol") or "").upper()
        ttype = _parse_type(get(row, "type"))
        tdate = _parse_date(get(row, "date"))
        if not symbol or ttype is None or tdate is None:
            continue
        shares = _num(get(row, "shares"))
        price = _num(get(row, "price"))
        value = _num(get(row, "value"))
        if value is None and shares is not None and price is not None:
            value = shares * price
        out.append(
            InsiderRow(symbol, get(row, "insider"), get(row, "title"), tdate, ttype,
                       shares, price, value)
        )
    return out


def ingest_psx_insider(db: Session, csv_path: Path | None = None) -> dict[str, int]:
    """Load PSX insider transactions from the CSV into insider_transactions."""
    from app.core.config import settings

    path = csv_path or Path(settings.psx_insider_csv)
    if not path.exists():
        log.warning("PSX insider CSV not found: %s", path)
        return {"rows": 0, "written": 0, "skipped_no_security": 0}
    return ingest_insider_text(db, path.read_text(encoding="utf-8"))


def ingest_insider_text(db: Session, text: str) -> dict[str, int]:
    rows = parse_insider_csv(text)
    psx = db.scalar(select(Market).where(Market.code == "PSX"))
    written = 0
    skipped = 0
    # Cache securities by symbol and their existing txn keys for idempotency.
    for r in rows:
        provider_symbol = f"{r.symbol}.KA"
        security = db.scalar(
            select(Security).where(Security.provider_symbol == provider_symbol)
        )
        if security is None:
            if psx is None:
                skipped += 1
                continue
            security = Security(
                market_id=psx.id, symbol=r.symbol, provider_symbol=provider_symbol,
                asset_class=AssetClass.EQUITY, currency="PKR", country="PK", is_active=True,
            )
            db.add(security)
            db.flush()

        exists = db.scalar(
            select(InsiderTransaction.id).where(
                InsiderTransaction.security_id == security.id,
                InsiderTransaction.transaction_date == r.transaction_date,
                InsiderTransaction.insider_name == r.insider,
                InsiderTransaction.transaction_type == r.transaction_type,
                InsiderTransaction.shares == r.shares,
            )
        )
        if exists is not None:
            continue  # idempotent: same trade already recorded
        db.add(
            InsiderTransaction(
                security_id=security.id,
                transaction_date=r.transaction_date,
                insider_name=r.insider,
                insider_title=r.title,
                transaction_type=r.transaction_type,
                shares=r.shares,
                price=r.price,
                value=r.value,
            )
        )
        written += 1
    db.commit()
    result = {"rows": len(rows), "written": written, "skipped_no_security": skipped}
    log.info("ingest_psx_insider: %s", result)
    return result
