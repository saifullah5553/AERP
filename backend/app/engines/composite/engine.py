"""Composite-scoring engine.

Blends the fundamental and technical scores (already stored) with freshly-derived
momentum, quality, and risk dimensions into the final composite:

    composite = 35% fundamental + 35% technical + 10% momentum + 10% quality + 10% risk

Weights are renormalised over whichever components are available, but a composite
is only produced when at least one of the two 35% anchors (fundamental/technical)
exists. The result and a full breakdown are written back to the latest ``scores``
row, and an actionable ``signals`` row is upserted.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.engines.common import f
from app.engines.composite.dimensions import momentum_score, risk_score
from app.engines.composite.regime_modifier import apply_regime_modifier
from app.engines.composite.signals import derive_signal
from app.models.fundamentals import FinancialRatios
from app.models.market import Security
from app.models.scoring import Score, Signal
from app.models.technical import TechnicalIndicator

log = get_logger(__name__)

# Weights are renormalised over whichever components a security actually has, so a component
# set to 0.0 simply stops influencing the composite (it is still computed and displayed).
#
# 2026-08-02, evidence-led weighting. Two measurements drove this:
#   * factor backtest: every technical input was a NEGATIVE predictor over 60d
#     (momentum IC -0.094, pct_from_52w_high -0.087, adx -0.086)
#   * point-in-time portfolio backtest using NO technicals at all beat the typical stock by
#     +65pp on PSX and +47pp on the ASX
# So fundamentals carry the ranking and technicals are demoted to a small timing contribution
# rather than a driver. They are not zeroed: the entry engine's price-action VETOES (don't
# chase an extended move) did add value, so some price awareness is retained.
WEIGHTS = {
    "fundamental": 0.75,
    "technical": 0.15,
    "momentum": 0.10,
    "quality": 0.0,
    "risk": 0.0,
}


@dataclass(slots=True)
class CompositeOutcome:
    security_id: int
    composite: float | None
    signal: str | None
    computed: bool


def _latest_score(db: Session, security_id: int) -> Score | None:
    return db.scalar(
        select(Score).where(Score.security_id == security_id).order_by(Score.as_of.desc())
    )


def _latest_ratios(db: Session, security_id: int) -> FinancialRatios | None:
    return db.scalar(
        select(FinancialRatios)
        .where(FinancialRatios.security_id == security_id)
        .order_by(FinancialRatios.fiscal_date.desc())
    )


def _latest_indicator(db: Session, security_id: int) -> TechnicalIndicator | None:
    return db.scalar(
        select(TechnicalIndicator)
        .where(TechnicalIndicator.security_id == security_id)
        .order_by(TechnicalIndicator.date.desc())
    )


def compute_for_security(
    db: Session, security: Security, regime_map: dict | None = None
) -> CompositeOutcome:
    score = _latest_score(db, security.id)
    if score is None:
        return CompositeOutcome(security.id, None, None, computed=False)

    ratios = _latest_ratios(db, security.id)
    indicator = _latest_indicator(db, security.id)

    mom, mom_bd = momentum_score(indicator)
    # The `quality` DIMENSION is gone. It scored a handful of ratios out of 100 and was shown
    # beside the fundamental score as a second opinion on the same question - 73 next to 86 on
    # Atlas Honda, neither of them the six-category score of 69.5. It carried 0.0 weight, so
    # nothing it said ever reached the composite; it only ever confused the page.
    qual, qual_bd = None, {}
    rsk, rsk_bd = risk_score(indicator, ratios)

    components: dict[str, float | None] = {
        "fundamental": f(score.fundamental),
        "technical": f(score.technical),
        "momentum": mom,
        "quality": qual,
        "risk": rsk,
    }

    anchor = components["fundamental"] is not None or components["technical"] is not None
    present = {k: v for k, v in components.items() if v is not None}
    if not anchor or not present:
        # Persist the component scores we do have, but no composite/signal.
        score.momentum, score.quality, score.risk = mom, qual, rsk
        db.commit()
        return CompositeOutcome(security.id, None, None, computed=False)

    total_w = sum(WEIGHTS[k] for k in present)
    base_composite = round(sum(v * WEIGHTS[k] for k, v in present.items()) / total_w, 2)
    coverage = round(total_w, 4)

    # Macro-regime overlay: bounded nudge from the security's country regime (dynamic,
    # country-relevant). No-op when no regime is available, so scores are unchanged unless
    # macro data is present.
    region = security.market.region.value if security.market else None
    regime = (regime_map or {}).get(region) if region else None
    de = f(ratios.debt_to_equity) if ratios is not None else None
    composite, regime_bd = apply_regime_modifier(base_composite, regime, de)

    signal = derive_signal(composite, coverage, present)

    # Persist component + composite scores and the breakdown.
    score.momentum, score.quality, score.risk, score.composite = mom, qual, rsk, composite
    merged = dict(score.breakdown or {})
    merged["composite"] = {
        "composite": composite,
        "base_composite": base_composite,
        "coverage": coverage,
        "weights": WEIGHTS,
        "components": {
            k: {"score": v, "weight": WEIGHTS[k],
                "contribution": round(v * WEIGHTS[k] / total_w, 2)}
            for k, v in present.items()
        },
        "dimensions": {"momentum": mom_bd, "quality": qual_bd, "risk": rsk_bd},
        "regime_modifier": regime_bd,
    }
    score.breakdown = merged

    _upsert_signal(db, security.id, score.as_of, signal, present)
    db.commit()

    return CompositeOutcome(security.id, composite, signal.signal.value, computed=True)


def _build_regime_map(db: Session) -> dict:
    """Per-country regime lookup for the modifier. Best-effort: any failure → {} (no-op)."""
    try:
        from app.ingestion.portfolio360 import Portfolio360Client
        from app.services.macro_regime import build_macro_regime

        pk = None
        try:
            pk = Portfolio360Client().pk_macro()
        except Exception:  # noqa: BLE001 - network optional
            pk = None
        return build_macro_regime(db, pk).get("countries", {}) or {}
    except Exception:  # noqa: BLE001 - regime overlay is optional
        return {}


def compute_all(db: Session, limit: int | None = None) -> dict[str, int]:
    sec_ids = db.scalars(select(Score.security_id).distinct()).all()
    if limit is not None:
        sec_ids = sec_ids[:limit]
    regime_map = _build_regime_map(db)
    scored = 0
    for sid in sec_ids:
        security = db.get(Security, sid)
        if security is None:
            continue
        outcome = compute_for_security(db, security, regime_map)
        if outcome.computed:
            scored += 1
    result = {"securities": len(sec_ids), "scored": scored, "regime_countries": len(regime_map)}
    log.info("compute_all composite: %s", result)
    return result


def _upsert_signal(
    db: Session, security_id: int, as_of, signal, components: dict[str, float]
) -> None:
    row = db.scalar(
        select(Signal).where(Signal.security_id == security_id, Signal.as_of == as_of)
    )
    if row is None:
        row = Signal(security_id=security_id, as_of=as_of)
        db.add(row)
    row.signal_type = signal.signal
    row.confidence = signal.confidence
    row.rationale = signal.rationale
    row.label = signal.label
    row.triggers = {k: round(v, 2) for k, v in components.items()}
