from __future__ import annotations

from fastapi.testclient import TestClient


def test_list_markets(client: TestClient) -> None:
    resp = client.get("/api/v1/markets")
    assert resp.status_code == 200
    codes = {m["code"] for m in resp.json()}
    assert {"NASDAQ", "PSX"} <= codes


def test_market_shape(client: TestClient) -> None:
    resp = client.get("/api/v1/markets")
    psx = next(m for m in resp.json() if m["code"] == "PSX")
    assert psx["region"] == "psx"
    assert psx["currency"] == "PKR"
    assert psx["ticker_suffix"] == ".KA"
