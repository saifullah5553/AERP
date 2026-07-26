"""Sector rotation + sector-average statistics, per market region.

Aggregates the platform's own per-stock scores and latest annual ratios into a
per-(region, sector) profile: average AI scores (composite/technical/fundamental/
Pabrai), median fundamentals (ROE/margins/growth/debt/valuation), a breadth-based
trend, and a momentum read. Powers the Sector Rotation dashboard (Feature 2) and the
Company-vs-Sector comparison (Feature 7) from one file. Recomputed each refresh, so it
tracks the market dynamically. No new data — pure aggregation of what we already have.
"""

from __future__ import annotations

import statistics
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.enums import AssetClass, StatementPeriod
from app.models.fundamentals import FinancialRatios
from app.models.market import Market, Security
from app.models.quote import Quote
from app.models.scoring import Score
from app.models.technical import TechnicalIndicator

log = get_logger(__name__)

# Median metrics surfaced for company-vs-sector comparison.
_METRICS = ["roe", "roic", "net_margin", "operating_margin", "revenue_growth",
            "eps_growth", "debt_to_equity", "pe_ratio"]


def _f(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _trend_label(above_ratio: float | None) -> str:
    if above_ratio is None:
        return "—"
    if above_ratio >= 0.7:
        return "Strong"
    if above_ratio >= 0.55:
        return "Improving"
    if above_ratio >= 0.4:
        return "Neutral"
    return "Weak"


def build_sector_stats(db: Session) -> dict:
    """{region: [sector-profile, ...]} sorted by average composite desc."""
    # Latest annual ratios per security.
    ratios: dict[int, FinancialRatios] = {}
    for fr in db.scalars(
        select(FinancialRatios).where(FinancialRatios.period == StatementPeriod.ANNUAL)
        .order_by(FinancialRatios.fiscal_date.asc())
    ):
        ratios[fr.security_id] = fr  # asc → last write wins = latest

    # Latest score per security.
    scores: dict[int, Score] = {}
    for sc in db.scalars(select(Score).order_by(Score.as_of.asc())):
        scores[sc.security_id] = sc

    # Above-SMA50 breadth per security (trend).
    above: dict[int, bool] = {}
    for sid, price, sma50 in db.execute(
        select(TechnicalIndicator.security_id, Quote.price, TechnicalIndicator.sma_50)
        .join(Quote, Quote.security_id == TechnicalIndicator.security_id, isouter=True)
    ).all():
        p, s = _f(price), _f(sma50)
        if p is not None and s:
            above[sid] = p > s

    # Group equities by (region, sector).
    buckets: dict[tuple, list[Security]] = defaultdict(list)
    for sec in db.scalars(
        select(Security).join(Market, Security.market_id == Market.id)
        .where(Security.asset_class == AssetClass.EQUITY, Security.is_active.is_(True),
               Security.sector.is_not(None))
    ):
        buckets[(sec.market.region.value, sec.sector)].append(sec)

    out: dict[str, list[dict]] = defaultdict(list)
    for (region, sector), secs in buckets.items():
        if len(secs) < 2:  # need a couple names for a meaningful sector stat
            continue
        ids = [s.id for s in secs]
        comps = [_f(scores[i].composite) for i in ids if i in scores]
        comps = [c for c in comps if c is not None]

        def _avg_of(attr: str, ids: list[int] = ids) -> list[float]:
            vals = [_f(getattr(scores[i], attr)) for i in ids if i in scores]
            return [v for v in vals if v is not None]

        techs = _avg_of("technical")
        funds = _avg_of("fundamental")
        pabs = _avg_of("pabrai")
        if not comps:
            continue
        breadth_vals = [above[i] for i in ids if i in above]
        above_ratio = (sum(breadth_vals) / len(breadth_vals)) if breadth_vals else None

        medians: dict[str, float | None] = {}
        for m in _METRICS:
            vals = [_f(getattr(ratios[i], m, None)) for i in ids if i in ratios]
            vals = [v for v in vals if v is not None]
            medians[m] = round(statistics.median(vals), 4) if vals else None

        avg_tech = round(statistics.fmean(techs), 1) if techs else None
        out[region].append({
            "sector": sector,
            "region": region,
            "count": len(secs),
            "score": round(statistics.fmean(comps), 1),
            "technical": avg_tech,
            "fundamental": round(statistics.fmean(funds), 1) if funds else None,
            "pabrai": round(statistics.fmean(pabs), 1) if pabs else None,
            "momentum": avg_tech,
            "breadth_above_50dma": round(above_ratio, 2) if above_ratio is not None else None,
            "trend": _trend_label(above_ratio),
            "medians": medians,
        })

    for region in out:
        out[region].sort(key=lambda s: s["score"], reverse=True)
    return dict(out)
