from __future__ import annotations

from fastapi.testclient import TestClient


def _auth(client: TestClient) -> dict[str, str]:
    client.post(
        "/api/v1/auth/register",
        json={"email": "wl@example.com", "password": "supersecret1"},
    )
    token = client.post(
        "/api/v1/auth/login", data={"username": "wl@example.com", "password": "supersecret1"}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_watchlist_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/watchlists").status_code == 401


def test_create_add_list(client: TestClient) -> None:
    headers = _auth(client)

    created = client.post("/api/v1/watchlists", json={"name": "Tech"}, headers=headers)
    assert created.status_code == 201
    wl_id = created.json()["id"]

    # AAPL exists in the seeded universe (conftest).
    added = client.post(
        f"/api/v1/watchlists/{wl_id}/items",
        json={"provider_symbol": "AAPL"},
        headers=headers,
    )
    assert added.status_code == 200
    assert len(added.json()["items"]) == 1

    listed = client.get("/api/v1/watchlists", headers=headers).json()
    assert len(listed) == 1
    assert listed[0]["name"] == "Tech"


def test_add_unknown_symbol_404(client: TestClient) -> None:
    headers = _auth(client)
    wl_id = client.post("/api/v1/watchlists", json={"name": "X"}, headers=headers).json()["id"]
    r = client.post(
        f"/api/v1/watchlists/{wl_id}/items",
        json={"provider_symbol": "NOPE.XX"},
        headers=headers,
    )
    assert r.status_code == 404
