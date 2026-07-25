"""Forward-looking analyst consensus via Yahoo (``yfinance``).

Populates each covered equity's next earnings date, consensus EPS/revenue estimate
for the current quarter, and the count of EPS estimate revisions in the last 30 days
(a simple analyst-sentiment read). These are published consensus figures, not our own
predictions. PSX is not covered by Yahoo, so those rows stay null.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.enums import AssetClass, MarketRegion
from app.models.market import Market, Security

log = get_logger(__name__)


@runtime_checkable
class EstimatesFetcher(Protocol):
    def raw(self, provider_symbol: str) -> dict[str, Any]: ...


@dataclass(slots=True)
class EstimateSummary:
    next_earnings_date: date | None = None
    eps_avg: float | None = None
    eps_num: int | None = None
    eps_growth: float | None = None
    rev_avg: float | None = None
    eps_up_30d: int | None = None
    eps_down_30d: int | None = None

    def is_empty(self) -> bool:
        return all(
            getattr(self, f) is None
            for f in ("next_earnings_date", "eps_avg", "rev_avg", "eps_up_30d", "eps_down_30d")
        )


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def _int(v: Any) -> int | None:
    f = _num(v)
    return int(f) if f is not None else None


def _pick_earnings_date(cal: dict[str, Any], today: date) -> date | None:
    raw = cal.get("Earnings Date") if isinstance(cal, dict) else None
    if raw is None:
        return None
    dates: list[date] = []
    for v in raw if isinstance(raw, list) else [raw]:
        if isinstance(v, datetime):
            dates.append(v.date())
        elif isinstance(v, date):
            dates.append(v)
        elif isinstance(v, str) and v.strip():
            with contextlib.suppress(ValueError):
                dates.append(datetime.fromisoformat(v.strip()[:19]).date())
    if not dates:
        return None
    upcoming = sorted(d for d in dates if d >= today)
    return upcoming[0] if upcoming else min(dates)


def normalize(raw: dict[str, Any], today: date | None = None) -> EstimateSummary:
    """Canned yfinance-shaped dicts → EstimateSummary (period frames keyed '0q','+1q'…)."""
    today = today or date.today()
    s = EstimateSummary()
    s.next_earnings_date = _pick_earnings_date(raw.get("calendar") or {}, today)

    eps = (raw.get("earnings_estimate") or {}).get("0q") or {}
    s.eps_avg = _num(eps.get("avg"))
    s.eps_num = _int(eps.get("numberOfAnalysts"))
    s.eps_growth = _num(eps.get("growth"))

    rev = (raw.get("revenue_estimate") or {}).get("0q") or {}
    s.rev_avg = _num(rev.get("avg"))

    rvs = (raw.get("eps_revisions") or {}).get("0q") or {}
    s.eps_up_30d = _int(rvs.get("upLast30days"))
    s.eps_down_30d = _int(rvs.get("downLast30days") or rvs.get("downLast30Days"))
    return s


def _frame_to_dict(df: Any) -> dict[str, dict[str, Any]]:
    if df is None or getattr(df, "empty", True):
        return {}
    return {str(idx): row.to_dict() for idx, row in df.iterrows()}


class YFinanceEstimatesFetcher:
    def raw(self, provider_symbol: str) -> dict[str, Any]:
        import yfinance as yf

        t = yf.Ticker(provider_symbol)
        cal = t.calendar if isinstance(t.calendar, dict) else {}
        return {
            "calendar": cal,
            "earnings_estimate": _frame_to_dict(getattr(t, "earnings_estimate", None)),
            "revenue_estimate": _frame_to_dict(getattr(t, "revenue_estimate", None)),
            "eps_revisions": _frame_to_dict(getattr(t, "eps_revisions", None)),
        }


def ingest_for_security(db: Session, fetcher: EstimatesFetcher, security: Security) -> bool:
    try:
        raw = fetcher.raw(security.provider_symbol)
    except Exception as exc:  # pragma: no cover - network dependent
        log.warning("Yahoo estimates failed for %s: %s", security.provider_symbol, exc)
        return False
    s = normalize(raw)
    if s.is_empty():
        return False
    security.next_earnings_date = s.next_earnings_date
    security.eps_estimate_avg = s.eps_avg
    security.eps_estimate_num = s.eps_num
    security.eps_estimate_growth = s.eps_growth
    security.revenue_estimate_avg = s.rev_avg
    security.eps_revisions_up_30d = s.eps_up_30d
    security.eps_revisions_down_30d = s.eps_down_30d
    return True


def ingest_estimates(
    db: Session,
    fetcher: EstimatesFetcher | None = None,
    region: MarketRegion | None = None,
    limit: int | None = None,
) -> dict[str, int]:
    fetcher = fetcher or YFinanceEstimatesFetcher()
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
    covered = 0
    for i, sec in enumerate(secs, 1):
        if ingest_for_security(db, fetcher, sec):
            covered += 1
        if i % 25 == 0:
            db.commit()
    db.commit()
    result = {"securities": len(secs), "covered": covered}
    log.info("ingest-estimates: %s", result)
    return result
