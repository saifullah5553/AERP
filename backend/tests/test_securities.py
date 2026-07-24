from __future__ import annotations

from fastapi.testclient import TestClient


def test_list_securities_paginated(client: TestClient) -> None:
    resp = client.get("/api/v1/securities", params={"page": 1, "page_size": 10})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert body["page"] == 1
    symbols = {item["symbol"] for item in body["items"]}
    assert symbols == {"AAPL", "LUCK"}


def test_search_securities(client: TestClient) -> None:
    resp = client.get("/api/v1/securities", params={"search": "apple"})
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["symbol"] == "AAPL"


def test_get_security_by_provider_symbol(client: TestClient) -> None:
    resp = client.get("/api/v1/securities/LUCK.KA")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Lucky Cement"


def test_get_security_404(client: TestClient) -> None:
    resp = client.get("/api/v1/securities/NOPE.XX")
    assert resp.status_code == 404
