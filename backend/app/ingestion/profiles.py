"""Company profile text (Yahoo ``longBusinessSummary``) for non-PSX equities.

Populates ``Security.long_business_summary`` — a factual company description published
by the data provider (not our own text). PSX is not covered by Yahoo, so those rows stay
null. Kept separate from the estimates step so it can run/refresh independently and its
one ``.info`` call per symbol doesn't slow the numeric ingestion.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.enums import AssetClass, MarketRegion
from app.models.market import Market, Security

log = get_logger(__name__)


@runtime_checkable
class ProfileFetcher(Protocol):
    def summary(self, provider_symbol: str) -> str | None: ...


class YFinanceProfileFetcher:
    def summary(self, provider_symbol: str) -> str | None:
        import yfinance as yf

        info = yf.Ticker(provider_symbol).info
        text = info.get("longBusinessSummary") if isinstance(info, dict) else None
        return text.strip() if isinstance(text, str) and text.strip() else None


def ingest_profiles(
    db: Session,
    fetcher: ProfileFetcher | None = None,
    region: MarketRegion | None = None,
    limit: int | None = None,
    refresh: bool = False,
) -> dict[str, int]:
    """Fetch business summaries for active equities. Skips PSX (uncovered by Yahoo) and,
    unless ``refresh``, any security that already has a summary (cheap, resumable)."""
    fetcher = fetcher or YFinanceProfileFetcher()
    stmt = (
        select(Security)
        .join(Market, Security.market_id == Market.id)
        .where(
            Security.asset_class == AssetClass.EQUITY,
            Security.is_active.is_(True),
            Market.region != MarketRegion.PSX,
        )
    )
    if region is not None:
        stmt = stmt.where(Market.region == region)
    if limit is not None:
        stmt = stmt.limit(limit)

    secs = db.scalars(stmt).all()
    covered = 0
    for i, sec in enumerate(secs, 1):
        if sec.long_business_summary and not refresh:
            covered += 1
            continue
        try:
            text = fetcher.summary(sec.provider_symbol)
        except Exception as exc:  # pragma: no cover - network dependent
            log.warning("Yahoo profile failed for %s: %s", sec.provider_symbol, exc)
            text = None
        if text:
            sec.long_business_summary = text
            covered += 1
        if i % 25 == 0:
            db.commit()
    db.commit()
    result: dict[str, Any] = {"securities": len(secs), "covered": covered}
    log.info("ingest-profiles: %s", result)
    return result
