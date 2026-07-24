from __future__ import annotations

from datetime import date, timedelta

import numpy as np
from app.engines.patterns.engine import compute_all, compute_for_security
from app.models.enums import AssetClass, MarketRegion
from app.models.market import Market, Security
from app.models.prices import DailyPrice
from app.models.technical import PatternDetection
from app.services.screener import ScreenerFilters, query_screener
from sqlalchemy import select
from sqlalchemy.orm import Session


def _double_bottom_close() -> np.ndarray:
    prices = [110.0, 80.0, 95.0, 81.0, 95.0]
    out: list[float] = []
    for i in range(len(prices) - 1):
        out.extend(np.linspace(prices[i], prices[i + 1], 8, endpoint=False).tolist())
    out.append(prices[-1])
    return np.array(out)


def _seed(db: Session) -> Security:
    market = Market(code="NASDAQ", name="NASDAQ", region=MarketRegion.US,
                    currency="USD", ticker_suffix="")
    db.add(market)
    db.flush()
    sec = Security(market_id=market.id, symbol="AAPL", provider_symbol="AAPL",
                   name="Apple", asset_class=AssetClass.EQUITY, currency="USD")
    db.add(sec)
    db.flush()

    close = _double_bottom_close()
    start = date(2025, 1, 1)
    for i, px in enumerate(close):
        db.add(DailyPrice(
            security_id=sec.id, date=start + timedelta(days=i),
            open=float(px), high=float(px) + 0.5, low=float(px) - 0.5,
            close=float(px), volume=1_000_000,
        ))
    db.commit()
    return sec


def test_engine_persists_active_patterns(db: Session) -> None:
    sec = _seed(db)
    outcome = compute_for_security(db, sec)

    assert outcome.computed is True
    assert outcome.detected > 0
    assert outcome.top_pattern is not None

    active = db.scalars(
        select(PatternDetection).where(
            PatternDetection.security_id == sec.id,
            PatternDetection.is_active.is_(True),
        )
    ).all()
    names = {p.name for p in active}
    assert "double_bottom" in names
    assert all(0 <= float(p.confidence) <= 1 for p in active)


def test_rerun_deactivates_prior_snapshot(db: Session) -> None:
    sec = _seed(db)
    compute_for_security(db, sec)
    first = db.scalar(select(PatternDetection).where(PatternDetection.security_id == sec.id))
    compute_for_security(db, sec)
    # The very first inserted row must now be inactive (snapshot replaced).
    db.refresh(first)
    assert first.is_active is False


def test_screener_surfaces_top_pattern(db: Session) -> None:
    sec = _seed(db)
    compute_for_security(db, sec)
    rows, total = query_screener(db, ScreenerFilters(), offset=0, limit=50)
    assert total == 1
    assert rows[0].top_pattern is not None


def test_compute_all_counts(db: Session) -> None:
    _seed(db)
    result = compute_all(db)
    assert result["securities"] == 1
    assert result["patterns"] > 0
