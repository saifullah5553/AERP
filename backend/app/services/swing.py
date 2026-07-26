"""Swing / positional Opportunity Score — a research ranking, not a trade signal.

Blends four already-computed, real dimensions into a 0–100 opportunity rank:

  * Fundamental Quality (40%) — the fundamental score (growth/returns/margins/balance sheet)
  * Business Catalyst  (25%) — sector strength + the live macro regime + raw-material cost
                               trend + earnings proximity (this leg reads the current
                               regime, so the ranking shifts automatically with macro)
  * Technical Setup    (25%) — the technical score (trend/MA/momentum/volume/breakout)
  * Risk               (10%) — the risk score (higher = lower risk)

Every input is real; the blend is a transparent ranking. No buy/sell, targets or
predictions. Computed at export from the DB scores + the freshly-built sector_stats /
macro_regime / raw_materials, so it recomputes each refresh.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.enums import AssetClass
from app.models.market import Market, Security
from app.models.quote import Quote
from app.models.scoring import Score

log = get_logger(__name__)

# Opportunity blend + catalyst sub-blend (configurable).
W = {"fundamental": 0.40, "catalyst": 0.25, "technical": 0.25, "risk": 0.10}
CW = {"sector": 0.40, "macro": 0.30, "raw_material": 0.20, "earnings": 0.10}


def _f(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _blend(parts: dict[str, float | None], weights: dict[str, float]) -> float | None:
    avail = {k: v for k, v in parts.items() if v is not None}
    if not avail:
        return None
    tw = sum(weights.get(k, 0.0) for k in avail)
    if tw == 0:
        return None
    return sum(avail[k] * weights.get(k, 0.0) for k in avail) / tw


def _raw_material_score(sector: str | None, industry: str | None, raw: dict | None) -> float | None:
    """Falling tracked input costs are supportive for a sector's margins."""
    if not raw:
        return None
    hay = f"{sector or ''} {industry or ''}".lower()
    syms: set[str] = set()
    for entry in raw.get("sector_map", []):
        if any(k in hay for k in entry.get("keywords", [])):
            syms.update(entry.get("materials", []))
    if not syms:
        return None
    commodities = raw.get("commodities", {})
    down = up = 0
    for s in syms:
        tr = (commodities.get(s) or {}).get("trend")
        if tr == "decreasing":
            down += 1
        elif tr == "increasing":
            up += 1
    if down == up:
        return 55.0
    return 70.0 if down > up else 40.0


def build_swing(
    db: Session,
    sector_stats: dict,
    regime: dict,
    raw_materials: dict | None,
) -> dict:
    """Ranked swing opportunities + a {provider_symbol: score} map for the screener."""
    # region → sector → sector score
    sector_score: dict[tuple[str, str], float] = {}
    for region, rows in (sector_stats or {}).items():
        for s in rows:
            sector_score[(region, s["sector"])] = s.get("score")
    # region → macro health
    health: dict[str, float | None] = {
        r: c.get("health") for r, c in (regime or {}).get("countries", {}).items()
    }
    today = datetime.now(tz=UTC).date()

    # latest score per security
    scores: dict[int, Score] = {}
    for sc in db.scalars(select(Score).order_by(Score.as_of.asc())):
        scores[sc.security_id] = sc

    ranked: list[dict] = []
    by_symbol: dict[str, float] = {}
    equities = db.scalars(
        select(Security).join(Market, Security.market_id == Market.id)
        .where(Security.asset_class == AssetClass.EQUITY, Security.is_active.is_(True))
    ).all()
    for sec in equities:
        sc = scores.get(sec.id)
        if sc is None or sc.fundamental is None or sc.technical is None:
            continue
        region = sec.market.region.value if sec.market else ""
        # Catalyst sub-scores
        earn = None
        if sec.next_earnings_date is not None:
            days = (sec.next_earnings_date - today).days
            earn = 66.0 if 0 <= days <= 30 else 52.0
        catalyst = _blend({
            "sector": sector_score.get((region, sec.sector or "")),
            "macro": health.get(region),
            "raw_material": _raw_material_score(sec.sector, sec.industry, raw_materials),
            "earnings": earn,
        }, CW)
        swing = _blend({
            "fundamental": _f(sc.fundamental),
            "catalyst": catalyst,
            "technical": _f(sc.technical),
            "risk": _f(sc.risk),
        }, W)
        if swing is None:
            continue
        swing = round(swing, 1)
        by_symbol[sec.provider_symbol] = swing
        q = db.get(Quote, sec.id)
        ranked.append({
            "provider_symbol": sec.provider_symbol,
            "symbol": sec.symbol,
            "name": sec.name,
            "market_code": sec.market.code if sec.market else None,
            "region": region,
            "sector": sec.sector,
            "swing_score": swing,
            "fundamental": _f(sc.fundamental),
            "catalyst": round(catalyst, 1) if catalyst is not None else None,
            "technical": _f(sc.technical),
            "risk": _f(sc.risk),
            "composite": _f(sc.composite),
            "price": _f(q.price) if q else None,
            "change_pct": _f(q.change_pct) if q else None,
        })

    ranked.sort(key=lambda r: r["swing_score"], reverse=True)
    log.info("build_swing: %d ranked", len(ranked))
    return {"ranked": ranked, "by_symbol": by_symbol}
