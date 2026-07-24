from __future__ import annotations

from datetime import date

from app.engines.composite.engine import compute_for_security
from app.models.enums import AssetClass, MarketRegion, StatementPeriod, Timeframe
from app.models.fundamentals import FinancialRatios
from app.models.market import Market, Security
from app.models.scoring import Score, Signal
from app.models.technical import TechnicalIndicator
from app.services.screener import ScreenerFilters, query_screener
from sqlalchemy import select
from sqlalchemy.orm import Session


def _security(db: Session) -> Security:
    market = Market(code="NASDAQ", name="NASDAQ", region=MarketRegion.US,
                    currency="USD", ticker_suffix="")
    db.add(market)
    db.flush()
    sec = Security(market_id=market.id, symbol="AAPL", provider_symbol="AAPL",
                   name="Apple", asset_class=AssetClass.EQUITY, currency="USD")
    db.add(sec)
    db.flush()
    return sec


def _inputs(db: Session, sec: Security, fundamental=80.0, technical=70.0) -> None:
    db.add(Score(security_id=sec.id, as_of=date.today(),
                 fundamental=fundamental, technical=technical,
                 breakdown={"fundamental": {}, "technical": {}}))
    db.add(FinancialRatios(security_id=sec.id, period=StatementPeriod.ANNUAL,
                           fiscal_date=date(2025, 12, 31), roe=0.20, net_margin=0.15,
                           gross_margin=0.5, piotroski_f=8, interest_coverage=9.0,
                           debt_to_equity=0.4, altman_z=3.5))
    db.add(TechnicalIndicator(security_id=sec.id, timeframe=Timeframe.D1,
                              date=date(2025, 12, 31), momentum=0.10, rsi_14=60,
                              pct_from_52w_high=-0.05, volatility=0.25))
    db.commit()


def test_composite_blends_and_signals(db: Session) -> None:
    sec = _security(db)
    _inputs(db, sec)
    outcome = compute_for_security(db, sec)

    assert outcome.computed is True
    assert outcome.composite is not None
    assert 60 <= outcome.composite <= 85  # dominated by the two 0.35 anchors

    score = db.scalar(select(Score).where(Score.security_id == sec.id))
    assert score.composite is not None
    assert score.momentum is not None and score.quality is not None and score.risk is not None
    comp_bd = score.breakdown["composite"]
    assert set(comp_bd["components"]) >= {"fundamental", "technical", "momentum", "quality", "risk"}

    signal = db.scalar(select(Signal).where(Signal.security_id == sec.id))
    assert signal is not None
    assert signal.triggers["fundamental"] == 80.0


def test_renormalises_when_fundamental_missing(db: Session) -> None:
    sec = _security(db)
    _inputs(db, sec, fundamental=None, technical=90.0)
    outcome = compute_for_security(db, sec)
    assert outcome.computed is True
    assert outcome.composite is not None
    # Technical anchor present; fundamental excluded from the weighting.
    comp_bd = db.scalar(select(Score).where(Score.security_id == sec.id)).breakdown["composite"]
    assert "fundamental" not in comp_bd["components"]


def test_no_anchor_no_composite(db: Session) -> None:
    sec = _security(db)
    # A score row with neither anchor, but momentum inputs exist.
    db.add(Score(security_id=sec.id, as_of=date.today(), breakdown={}))
    db.add(TechnicalIndicator(security_id=sec.id, timeframe=Timeframe.D1,
                              date=date(2025, 12, 31), momentum=0.1, rsi_14=60,
                              pct_from_52w_high=-0.05, volatility=0.25))
    db.commit()

    outcome = compute_for_security(db, sec)
    assert outcome.computed is False
    assert outcome.composite is None
    score = db.scalar(select(Score).where(Score.security_id == sec.id))
    assert score.composite is None
    assert score.momentum is not None  # component still persisted


def test_screener_surfaces_composite_and_signal(db: Session) -> None:
    sec = _security(db)
    _inputs(db, sec)
    compute_for_security(db, sec)
    rows, total = query_screener(db, ScreenerFilters(), offset=0, limit=50)
    assert total == 1
    assert rows[0].composite_score is not None
    assert rows[0].signal is not None
    assert rows[0].signal_label is not None
