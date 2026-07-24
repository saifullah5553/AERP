"""Test fixtures.

The suite runs entirely against an in-memory SQLite database with the schema
built from the ORM metadata, so it needs no Postgres/Redis/Docker. The FastAPI
``get_db`` dependency is overridden to use the test session.

A single shared in-memory connection (``StaticPool``) backs the engine, so all
sessions in a test observe the same data. The schema is created and dropped per
test for isolation.
"""

from __future__ import annotations

import os

# Must be set before app modules import settings (cached at import time).
os.environ.setdefault("AERP_SEED_ON_STARTUP", "false")
os.environ.setdefault("AERP_ENV", "test")

from datetime import date  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402
from app.models.enums import AssetClass, MarketRegion, SignalType  # noqa: E402
from app.models.fundamentals import FundamentalSnapshot  # noqa: E402
from app.models.market import Market, Security  # noqa: E402
from app.models.quote import Quote  # noqa: E402
from app.models.scoring import Score, Signal  # noqa: E402

engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    future=True,
)
TestSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def db() -> Session:
    Base.metadata.create_all(bind=engine)
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def seeded(db: Session) -> Session:
    """A small, deterministic universe exercising every screener join."""
    nasdaq = Market(
        code="NASDAQ", name="NASDAQ", region=MarketRegion.US, country="US",
        currency="USD", ticker_suffix="", is_active=True,
    )
    psx = Market(
        code="PSX", name="Pakistan Stock Exchange", region=MarketRegion.PSX,
        country="PK", currency="PKR", ticker_suffix=".KA", is_active=True,
    )
    db.add_all([nasdaq, psx])
    db.flush()

    aapl = Security(
        market_id=nasdaq.id, symbol="AAPL", provider_symbol="AAPL",
        name="Apple Inc.", asset_class=AssetClass.EQUITY, sector="Technology",
        industry="Consumer Electronics", currency="USD", country="US",
        market_cap=3_000_000_000_000, is_active=True,
    )
    luck = Security(
        market_id=psx.id, symbol="LUCK", provider_symbol="LUCK.KA",
        name="Lucky Cement", asset_class=AssetClass.EQUITY, sector="Materials",
        industry="Cement", currency="PKR", country="PK", is_active=True,
    )
    db.add_all([aapl, luck])
    db.flush()

    # AAPL gets a full set of downstream rows; LUCK is left bare to prove that a
    # security with no price/score still appears (with NULLs) via LEFT joins.
    db.add(Quote(security_id=aapl.id, price=200.0, prev_close=196.0, change=4.0,
                 change_pct=2.04, volume=50_000_000))
    db.add(FundamentalSnapshot(security_id=aapl.id, as_of=date(2026, 6, 30),
                               pe_ttm=30.5, roe=1.5, debt_to_equity=1.2,
                               revenue_growth=0.08, eps_growth=0.11,
                               dividend_yield=0.005))
    db.add(Score(security_id=aapl.id, as_of=date(2026, 7, 24), fundamental=82,
                 technical=74, momentum=70, quality=88, risk=60, composite=78))
    db.add(Signal(security_id=aapl.id, as_of=date(2026, 7, 24),
                  signal_type=SignalType.BUY, confidence=0.72, label="Buy"))
    db.commit()
    return db


@pytest.fixture()
def client(seeded: Session) -> TestClient:
    def _override_get_db():
        session = TestSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
