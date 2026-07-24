from __future__ import annotations

from fastapi.testclient import TestClient


def test_screener_returns_all_active(client: TestClient) -> None:
    resp = client.get("/api/v1/screener")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    by_symbol = {r["symbol"]: r for r in body["items"]}
    assert set(by_symbol) == {"AAPL", "LUCK"}


def test_screener_joins_price_and_score(client: TestClient) -> None:
    body = client.get("/api/v1/screener").json()
    aapl = next(r for r in body["items"] if r["symbol"] == "AAPL")
    assert aapl["price"] == 200.0
    assert aapl["change_pct"] == 2.04
    assert aapl["composite_score"] == 78.0
    assert aapl["signal"] == "buy"
    assert aapl["market_code"] == "NASDAQ"
    assert aapl["region"] == "us"


def test_screener_shows_nulls_not_fabricated(client: TestClient) -> None:
    # LUCK has no quote/score seeded — it must still appear, with NULL analytics.
    body = client.get("/api/v1/screener").json()
    luck = next(r for r in body["items"] if r["symbol"] == "LUCK")
    assert luck["price"] is None
    assert luck["composite_score"] is None
    assert luck["signal"] is None


def test_screener_filter_by_region(client: TestClient) -> None:
    body = client.get("/api/v1/screener", params={"region": "psx"}).json()
    assert body["total"] == 1
    assert body["items"][0]["symbol"] == "LUCK"


def test_screener_min_composite_filter(client: TestClient) -> None:
    body = client.get("/api/v1/screener", params={"min_composite": 50}).json()
    # Only AAPL has a composite (78); LUCK's NULL is excluded by the threshold.
    assert body["total"] == 1
    assert body["items"][0]["symbol"] == "AAPL"


def test_screener_sort_desc_puts_nulls_last(client: TestClient) -> None:
    body = client.get(
        "/api/v1/screener",
        params={"sort_by": "composite_score", "sort_dir": "desc"},
    ).json()
    symbols = [r["symbol"] for r in body["items"]]
    # AAPL (78) ranks above LUCK (NULL → last).
    assert symbols == ["AAPL", "LUCK"]


def test_screener_columns_contract(client: TestClient) -> None:
    resp = client.get("/api/v1/screener/columns")
    assert resp.status_code == 200
    fields = {c["field"] for c in resp.json()}
    assert {"symbol", "price", "composite_score", "signal"} <= fields
