"""Insider-activity engine — trailing-window buy/sell analysis with a 0–100 score.

For each security it looks at open-market insider **purchases** and **sales** in
the trailing window (default 60 days) and produces:
- a value-weighted score (100 = heavy net buying, 0 = heavy net selling), and
- a plain-language ``activity`` label,
persisted to ``insider_summaries``. Grants/option-exercises are ignored for the
buy/sell signal. No open-market trades in the window → score NULL, "no_activity".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.corporate import InsiderSummary, InsiderTransaction
from app.models.enums import InsiderTransactionType
from app.models.market import Security

log = get_logger(__name__)

WINDOW_DAYS = 60


@dataclass(slots=True)
class InsiderResult:
    score: float | None
    activity: str
    buy_value: float
    sell_value: float
    buy_count: int
    sell_count: int


def _label(score: float | None) -> str:
    if score is None:
        return "no_activity"
    if score >= 80:
        return "strong_buying"
    if score >= 60:
        return "buying"
    if score > 40:
        return "neutral"
    if score > 20:
        return "selling"
    return "strong_selling"


def analyze(
    transactions: list[InsiderTransaction], as_of: date, window: int = WINDOW_DAYS
) -> InsiderResult:
    """Pure scoring over a list of insider transactions."""
    cutoff = as_of - timedelta(days=window)
    buy_value = sell_value = 0.0
    buyers: set[str] = set()
    sellers: set[str] = set()
    for t in transactions:
        if t.transaction_date is None or t.transaction_date < cutoff:
            continue
        value = float(t.value) if t.value is not None else (
            float(t.shares or 0) * float(t.price or 0)
        )
        who = (t.insider_name or "?").strip().lower()
        if t.transaction_type == InsiderTransactionType.BUY:
            buy_value += abs(value)
            buyers.add(who)
        elif t.transaction_type == InsiderTransactionType.SELL:
            sell_value += abs(value)
            sellers.add(who)

    total = buy_value + sell_value
    if total <= 0:
        return InsiderResult(None, "no_activity", 0.0, 0.0, 0, 0)
    score = round(100.0 * buy_value / total, 2)
    return InsiderResult(score, _label(score), buy_value, sell_value, len(buyers), len(sellers))


def compute_for_security(
    db: Session, security: Security, window: int = WINDOW_DAYS, as_of: date | None = None
) -> InsiderResult:
    txns = list(
        db.scalars(
            select(InsiderTransaction).where(InsiderTransaction.security_id == security.id)
        )
    )
    today = as_of or date.today()
    result = analyze(txns, today, window)

    summary = db.get(InsiderSummary, security.id)
    if summary is None:
        summary = InsiderSummary(security_id=security.id)
        db.add(summary)
    summary.as_of = today
    summary.window_days = window
    summary.buy_count = result.buy_count
    summary.sell_count = result.sell_count
    summary.buy_value = result.buy_value
    summary.sell_value = result.sell_value
    summary.net_value = result.buy_value - result.sell_value
    summary.score = result.score
    summary.activity = result.activity
    db.commit()
    return result


def compute_all(db: Session, limit: int | None = None) -> dict[str, int]:
    sec_ids = db.scalars(
        select(InsiderTransaction.security_id).distinct()
    ).all()
    if limit is not None:
        sec_ids = sec_ids[:limit]
    active = 0
    for sid in sec_ids:
        security = db.get(Security, sid)
        if security is None:
            continue
        result = compute_for_security(db, security)
        if result.score is not None and result.activity not in {"no_activity", "neutral"}:
            active += 1
    out = {"securities": len(sec_ids), "with_signal": active}
    log.info("compute_all insider: %s", out)
    return out
