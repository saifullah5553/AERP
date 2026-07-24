from __future__ import annotations

from datetime import date

from app.models.enums import (
    AssetClass,
    MarketRegion,
    PatternCategory,
    PatternDirection,
    StatementPeriod,
    Timeframe,
)
from app.models.fundamentals import IncomeStatement
from app.models.market import Market, Security
from app.models.scoring import Score
from app.models.technical import PatternDetection
from app.services.company import get_company
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


# ── Endpoint tests (use the seeded AAPL/LUCK universe from conftest) ──────────
def test_company_endpoint_aapl(client: TestClient) -> None:
    resp = client.get("/api/v1/company/AAPL")
    assert resp.status_code == 200
    body = resp.json()
    assert body["security"]["symbol"] == "AAPL"
    assert body["security"]["market_code"] == "NASDAQ"
    assert body["tradingview_symbol"] == "NASDAQ:AAPL"
    assert body["scores"]["composite"] == 78.0
    assert body["signal"]["label"] == "Buy"
    assert isinstance(body["ai_summary"], str) and len(body["ai_summary"]) > 0
    # Structural keys always present, even when empty.
    for key in ("statements", "patterns", "score_history", "peers", "dividends"):
        assert key in body


def test_company_404(client: TestClient) -> None:
    assert client.get("/api/v1/company/NOPE.XX").status_code == 404


def test_tradingview_symbol_crypto(client: TestClient) -> None:
    # LUCK is PSX (no TV feed) → null; verify the null path is honest.
    body = client.get("/api/v1/company/LUCK.KA").json()
    assert body["tradingview_symbol"] is None


# ── Service test with richer data ────────────────────────────────────────────
def test_get_company_aggregates(db: Session) -> None:
    market = Market(code="NASDAQ", name="NASDAQ", region=MarketRegion.US,
                    currency="USD", ticker_suffix="")
    db.add(market)
    db.flush()
    aapl = Security(market_id=market.id, symbol="AAPL", provider_symbol="AAPL",
                    name="Apple", asset_class=AssetClass.EQUITY, sector="Technology")
    msft = Security(market_id=market.id, symbol="MSFT", provider_symbol="MSFT",
                    name="Microsoft", asset_class=AssetClass.EQUITY, sector="Technology")
    db.add_all([aapl, msft])
    db.flush()

    db.add(IncomeStatement(security_id=aapl.id, period=StatementPeriod.ANNUAL,
                           fiscal_date=date(2025, 12, 31), revenue=1200, net_income=236))
    db.add(PatternDetection(security_id=aapl.id, timeframe=Timeframe.D1,
                            detected_on=date(2026, 1, 2), name="cup_and_handle",
                            category=PatternCategory.CHART, direction=PatternDirection.BULLISH,
                            confidence=0.8, is_active=True))
    db.add(Score(security_id=aapl.id, as_of=date(2026, 1, 1), composite=70, fundamental=72))
    db.add(Score(security_id=aapl.id, as_of=date(2026, 1, 2), composite=78, fundamental=80))
    db.add(Score(security_id=msft.id, as_of=date(2026, 1, 2), composite=85))
    db.commit()

    detail = get_company(db, "AAPL")
    assert detail is not None
    assert len(detail.statements["income"]) == 1
    assert detail.patterns[0]["name"] == "cup_and_handle"
    # Latest score is the 2026-01-02 row; history keeps both ascending.
    assert detail.scores["composite"] == 78.0
    assert [p.composite for p in detail.score_history] == [70.0, 78.0]
    # MSFT is a same-sector peer.
    assert any(p.symbol == "MSFT" for p in detail.peers)
    assert "cup and handle" in detail.ai_summary
