from __future__ import annotations

from datetime import date, timedelta

import pytest
from app.engines.technical.engine import compute_all, compute_for_security
from app.models.enums import AssetClass, MarketRegion, Timeframe
from app.models.market import Market, Security
from app.models.prices import DailyPrice
from app.models.scoring import Score
from app.models.technical import TechnicalIndicator
from sqlalchemy import select
from sqlalchemy.orm import Session


def _seed_security(db: Session, n: int = 260, step: float = 0.5) -> Security:
    market = Market(code="NASDAQ", name="NASDAQ", region=MarketRegion.US,
                    currency="USD", ticker_suffix="")
    db.add(market)
    db.flush()
    sec = Security(market_id=market.id, symbol="AAPL", provider_symbol="AAPL",
                   name="Apple", asset_class=AssetClass.EQUITY, currency="USD")
    db.add(sec)
    db.flush()

    start = date(2025, 1, 1)
    for i in range(n):
        close = 100.0 + i * step
        db.add(DailyPrice(
            security_id=sec.id, date=start + timedelta(days=i),
            open=close - 0.2, high=close + 0.5, low=close - 0.5,
            close=close, adj_close=close, volume=1_000_000 + i,
        ))
    db.commit()
    return sec


def test_compute_persists_indicators_and_score(db: Session) -> None:
    sec = _seed_security(db)
    outcome = compute_for_security(db, sec)

    assert outcome.computed is True
    assert outcome.score is not None and outcome.score > 70  # clean uptrend
    assert outcome.coverage == 1.0

    ind = db.scalar(
        select(TechnicalIndicator).where(TechnicalIndicator.security_id == sec.id)
    )
    assert ind is not None
    assert ind.timeframe == Timeframe.D1
    assert float(ind.rsi_14) == pytest.approx(100.0)
    assert ind.supertrend_dir == 1

    score = db.scalar(select(Score).where(Score.security_id == sec.id, Score.as_of == date.today()))
    assert float(score.technical) == pytest.approx(outcome.score)
    assert "metrics" in score.breakdown["technical"]


def test_score_merge_preserves_fundamental(db: Session) -> None:
    sec = _seed_security(db)
    db.add(Score(security_id=sec.id, as_of=date.today(), fundamental=80.0,
                 breakdown={"fundamental": {"score": 80.0}}))
    db.commit()

    compute_for_security(db, sec)
    score = db.scalar(select(Score).where(Score.security_id == sec.id, Score.as_of == date.today()))
    assert float(score.fundamental) == 80.0    # preserved
    assert score.technical is not None          # added
    assert {"fundamental", "technical"} <= set(score.breakdown)


def test_too_few_bars_not_computed(db: Session) -> None:
    sec = _seed_security(db, n=5)
    outcome = compute_for_security(db, sec)
    assert outcome.computed is False


def test_compute_all_counts(db: Session) -> None:
    _seed_security(db)
    result = compute_all(db)
    assert result["securities"] == 1
    assert result["scored"] == 1
