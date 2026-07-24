"""Forex fundamental engine — macro-driven.

A currency pair's "fundamental" is the relative health of the two economies. We
score each currency's country from stored macro indicators (growth, inflation,
real rates, unemployment, external balance), then map the base-minus-quote
strength differential to a 0–100 fundamental score for the pair and write it to
the ``scores`` row — so the composite engine treats forex just like equities.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.engines.common import clamp
from app.engines.scoring_util import Spec, band, higher_better, lower_better, weighted_score
from app.ingestion.macro import CURRENCY_COUNTRY
from app.models.enums import AssetClass
from app.models.enums import MacroIndicatorType as M
from app.models.macro import MacroIndicator
from app.models.market import Security
from app.models.scoring import Score

log = get_logger(__name__)

# Currency-strength rubric. Inflation is a band (≈2% ideal); everything else is
# monotonic. Keys match MacroIndicatorType values.
STRENGTH_SPECS = [
    Spec(M.GDP_GROWTH.value, 0.30, higher_better(-2.0, 5.0), "GDP growth %"),
    Spec(M.REAL_INTEREST_RATE.value, 0.25, higher_better(-2.0, 6.0), "Real interest rate %"),
    Spec(M.CPI_INFLATION.value, 0.20, band(1.0, 3.0, -2.0, 12.0), "CPI inflation %"),
    Spec(M.UNEMPLOYMENT.value, 0.15, lower_better(3.0, 12.0), "Unemployment %"),
    Spec(M.CURRENT_ACCOUNT.value, 0.10, higher_better(-8.0, 8.0), "Current account % GDP"),
]


@dataclass(slots=True)
class ForexOutcome:
    security_id: int
    score: float | None
    computed: bool


def _latest_macro(db: Session, country: str) -> dict[str, float | None]:
    rows = db.scalars(
        select(MacroIndicator)
        .where(MacroIndicator.country == country)
        .order_by(MacroIndicator.period_date.desc())
    ).all()
    latest: dict[str, float | None] = {}
    for r in rows:
        key = r.indicator.value
        if key not in latest:  # first seen == most recent (desc order)
            latest[key] = float(r.value) if r.value is not None else None
    return latest


def _currency_strength(db: Session, currency: str) -> tuple[float | None, dict[str, Any]]:
    country = CURRENCY_COUNTRY.get(currency)
    if country is None:
        return None, {"reason": "unmapped_currency", "currency": currency}
    metrics = _latest_macro(db, country)
    result = weighted_score(STRENGTH_SPECS, metrics)
    bd = {"currency": currency, "country": country, **result.breakdown}
    return result.score, bd


def compute_for_security(db: Session, security: Security) -> ForexOutcome:
    if security.asset_class != AssetClass.FOREX or len(security.symbol) != 6:
        return ForexOutcome(security.id, None, computed=False)

    base, quote = security.symbol[:3], security.symbol[3:]
    base_score, base_bd = _currency_strength(db, base)
    quote_score, quote_bd = _currency_strength(db, quote)
    if base_score is None or quote_score is None:
        return ForexOutcome(security.id, None, computed=False)

    # Base stronger than quote → the pair (base/quote) is fundamentally bid.
    pair_score = round(clamp(50.0 + (base_score - quote_score) / 2.0), 2)
    _persist_score(db, security.id, pair_score, base, quote, base_score, quote_score,
                   base_bd, quote_bd)
    db.commit()
    return ForexOutcome(security.id, pair_score, computed=True)


def compute_all(db: Session, limit: int | None = None) -> dict[str, int]:
    sec_ids = db.scalars(
        select(Security.id).where(
            Security.asset_class == AssetClass.FOREX, Security.is_active.is_(True)
        )
    ).all()
    if limit is not None:
        sec_ids = sec_ids[:limit]
    scored = 0
    for sid in sec_ids:
        security = db.get(Security, sid)
        if security is None:
            continue
        outcome = compute_for_security(db, security)
        if outcome.computed:
            scored += 1
    result = {"forex": len(sec_ids), "scored": scored}
    log.info("compute_all forex: %s", result)
    return result


def _persist_score(
    db: Session,
    security_id: int,
    pair_score: float,
    base: str,
    quote: str,
    base_score: float,
    quote_score: float,
    base_bd: dict,
    quote_bd: dict,
) -> None:
    today = date.today()
    row = db.scalar(
        select(Score).where(Score.security_id == security_id, Score.as_of == today)
    )
    if row is None:
        row = Score(security_id=security_id, as_of=today)
        db.add(row)
    row.fundamental = pair_score
    merged = dict(row.breakdown or {})
    merged["fundamental"] = {
        "type": "forex_macro",
        "score": pair_score,
        "pair": f"{base}/{quote}",
        "base_strength": base_score,
        "quote_strength": quote_score,
        "base": base_bd,
        "quote": quote_bd,
    }
    row.breakdown = merged
