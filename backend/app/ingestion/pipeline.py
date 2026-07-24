"""Ingestion orchestration.

Pure functions that take a DB session and a provider registry, so they are unit-
testable without Celery or a real network. The Celery tasks in
``app.tasks.ingestion`` are thin wrappers that supply a real session and registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.cache import publish
from app.core.logging import get_logger
from app.ingestion.registry import ProviderRegistry, SecurityRef
from app.ingestion.repository import (
    markets_by_code,
    upsert_daily_bars,
    upsert_quote,
    upsert_security,
    upsert_statements,
)
from app.models.enums import AssetClass, MarketRegion
from app.models.market import Market, Security

log = get_logger(__name__)


@dataclass(slots=True)
class RefreshResult:
    requested: int
    resolved: int


def _active_security_refs(
    db: Session, region: MarketRegion | None, limit: int | None
) -> tuple[list[SecurityRef], dict[str, int]]:
    """Return routing refs for active securities and a symbol→id map."""
    stmt = (
        select(
            Security.id,
            Security.provider_symbol,
            Security.asset_class,
            Market.region,
        )
        .join(Market, Security.market_id == Market.id)
        .where(Security.is_active.is_(True))
    )
    if region is not None:
        stmt = stmt.where(Market.region == region)
    if limit is not None:
        stmt = stmt.limit(limit)

    refs: list[SecurityRef] = []
    id_by_symbol: dict[str, int] = {}
    for sec_id, provider_symbol, asset_class, sec_region in db.execute(stmt):
        refs.append(SecurityRef(provider_symbol, asset_class, sec_region))
        id_by_symbol[provider_symbol] = sec_id
    return refs, id_by_symbol


def refresh_quotes(
    db: Session,
    registry: ProviderRegistry,
    region: MarketRegion | None = None,
    limit: int | None = None,
) -> RefreshResult:
    """Fetch latest quotes for active securities and upsert the snapshot table."""
    refs, id_by_symbol = _active_security_refs(db, region, limit)
    if not refs:
        return RefreshResult(requested=0, resolved=0)

    quotes = registry.get_quotes(refs)
    for provider_symbol, dto in quotes.items():
        security_id = id_by_symbol.get(provider_symbol)
        if security_id is None:
            continue
        upsert_quote(db, security_id, dto)
        publish(
            "quotes",
            {
                "symbol": provider_symbol,
                "price": dto.price,
                "change_pct": dto.change_pct,
            },
        )
    db.commit()
    log.info("refresh_quotes: %d requested, %d resolved", len(refs), len(quotes))
    return RefreshResult(requested=len(refs), resolved=len(quotes))


def backfill_daily(
    db: Session,
    registry: ProviderRegistry,
    region: MarketRegion | None = None,
    start: date | None = None,
    limit: int | None = None,
) -> int:
    """Backfill/append daily OHLCV for active securities. Returns bars written."""
    refs, id_by_symbol = _active_security_refs(db, region, limit)
    total = 0
    for ref in refs:
        bars = registry.get_daily(ref, start)
        if not bars:
            continue
        security_id = id_by_symbol[ref.provider_symbol]
        total += upsert_daily_bars(db, security_id, bars)
        db.commit()  # commit per security so a later failure keeps earlier work
    log.info("backfill_daily: %d bars written across %d securities", total, len(refs))
    return total


def ingest_fundamentals(
    db: Session,
    registry: ProviderRegistry,
    region: MarketRegion | None = None,
    limit: int | None = None,
) -> dict[str, int]:
    """Fetch and store financial statements for active equities."""
    refs, id_by_symbol = _active_security_refs(db, region, limit)
    equities = [r for r in refs if r.asset_class == AssetClass.EQUITY]
    covered = 0
    statements_written = 0
    for ref in equities:
        stmts = registry.get_statements(ref)
        if not stmts:
            continue
        security_id = id_by_symbol[ref.provider_symbol]
        statements_written += upsert_statements(db, security_id, stmts)
        covered += 1
        db.commit()
    result = {
        "equities": len(equities),
        "covered": covered,
        "statements_written": statements_written,
    }
    log.info("ingest_fundamentals: %s", result)
    return result


def load_universe(
    db: Session,
    registry: ProviderRegistry,
    provider_names: list[str] | None = None,
) -> dict[str, int]:
    """Discover securities from providers and upsert them into their markets."""
    profiles = registry.discover_universe(provider_names)
    markets = markets_by_code(db)
    created = 0
    skipped_no_market = 0

    for profile in profiles:
        market: Market | None = markets.get(profile.exchange or "")
        if market is None:
            skipped_no_market += 1
            continue
        _, was_created = upsert_security(db, market, profile)
        if was_created:
            created += 1
    db.commit()

    result = {
        "discovered": len(profiles),
        "created": created,
        "skipped_no_market": skipped_no_market,
    }
    log.info("load_universe: %s", result)
    return result
