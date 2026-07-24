from __future__ import annotations

from datetime import date

import pytest
from app.engines.fundamental.engine import compute_all, compute_for_security
from app.models.enums import AssetClass, MarketRegion
from app.models.fundamentals import FinancialRatios, FundamentalSnapshot
from app.models.market import Market, Security
from app.models.quote import Quote
from app.models.scoring import Score
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests import fundamentals_data as fd


@pytest.fixture()
def security_with_statements(db: Session) -> tuple[Session, Security]:
    market = Market(code="NASDAQ", name="NASDAQ", region=MarketRegion.US,
                    currency="USD", ticker_suffix="")
    db.add(market)
    db.flush()
    sec = Security(market_id=market.id, symbol="AAPL", provider_symbol="AAPL",
                   name="Apple", asset_class=AssetClass.EQUITY, currency="USD",
                   shares_outstanding=100.0)
    db.add(sec)
    db.flush()

    for row in fd.incomes(sec.id) + fd.balances(sec.id) + fd.cashflows(sec.id):
        db.add(row)
    db.add(Quote(security_id=sec.id, price=50.0))
    db.commit()
    return db, sec


def test_compute_for_security_persists_everything(
    security_with_statements: tuple[Session, Security],
) -> None:
    db, sec = security_with_statements
    outcome = compute_for_security(db, sec)

    assert outcome.computed is True
    assert outcome.score is not None and outcome.score > 70  # strong fundamentals
    assert outcome.coverage == 1.0

    ratios = db.scalar(select(FinancialRatios).where(FinancialRatios.security_id == sec.id))
    assert ratios is not None
    assert float(ratios.roe) == pytest.approx(236 / 1075, rel=1e-3)
    assert ratios.piotroski_f == 9

    snap = db.get(FundamentalSnapshot, sec.id)
    assert snap is not None
    assert float(snap.pe_ttm) == pytest.approx(5000 / 236, rel=1e-3)

    score = db.scalar(select(Score).where(Score.security_id == sec.id, Score.as_of == date.today()))
    assert score is not None
    assert float(score.fundamental) == pytest.approx(outcome.score)
    # Breakdown is stored and explainable.
    assert "metrics" in score.breakdown["fundamental"]
    assert score.breakdown["fundamental"]["piotroski_criteria"]["positive_ocf"] is True


def test_compute_score_preserves_prior_breakdown(
    security_with_statements: tuple[Session, Security],
) -> None:
    db, sec = security_with_statements
    # Simulate a technical run having already written today's score.
    existing = Score(security_id=sec.id, as_of=date.today(), technical=55.0,
                     breakdown={"technical": {"score": 55.0}})
    db.add(existing)
    db.commit()

    compute_for_security(db, sec)
    score = db.scalar(select(Score).where(Score.security_id == sec.id, Score.as_of == date.today()))
    assert float(score.technical) == 55.0  # preserved
    assert score.fundamental is not None    # added
    assert "technical" in score.breakdown and "fundamental" in score.breakdown


def test_compute_all_counts(security_with_statements: tuple[Session, Security]) -> None:
    db, _ = security_with_statements
    result = compute_all(db)
    assert result["securities"] == 1
    assert result["scored"] == 1


def test_security_without_statements_not_computed(db: Session) -> None:
    market = Market(code="PSX", name="PSX", region=MarketRegion.PSX,
                    currency="PKR", ticker_suffix=".KA")
    db.add(market)
    db.flush()
    sec = Security(market_id=market.id, symbol="LUCK", provider_symbol="LUCK.KA",
                   name="Lucky", asset_class=AssetClass.EQUITY, currency="PKR")
    db.add(sec)
    db.commit()

    outcome = compute_for_security(db, sec)
    assert outcome.computed is False
    assert outcome.score is None
