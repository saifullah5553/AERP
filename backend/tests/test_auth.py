from __future__ import annotations

from fastapi.testclient import TestClient

CREDS = {"email": "trader@example.com", "password": "supersecret1", "full_name": "Trader"}


def _register(client: TestClient, **over) -> None:
    client.post("/api/v1/auth/register", json={**CREDS, **over})


def _token(client: TestClient, email=CREDS["email"], password=CREDS["password"]) -> str:
    resp = client.post(
        "/api/v1/auth/login", data={"username": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def test_register_and_login_and_me(client: TestClient) -> None:
    r = client.post("/api/v1/auth/register", json=CREDS)
    assert r.status_code == 201
    assert r.json()["email"] == CREDS["email"]
    assert r.json()["is_superuser"] is False

    token = _token(client)
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == CREDS["email"]


def test_duplicate_register_rejected(client: TestClient) -> None:
    _register(client)
    r = client.post("/api/v1/auth/register", json=CREDS)
    assert r.status_code == 400


def test_login_wrong_password(client: TestClient) -> None:
    _register(client)
    r = client.post(
        "/api/v1/auth/login", data={"username": CREDS["email"], "password": "wrong-pass"}
    )
    assert r.status_code == 401


def test_me_requires_token(client: TestClient) -> None:
    assert client.get("/api/v1/auth/me").status_code == 401


def test_weak_password_rejected(client: TestClient) -> None:
    r = client.post(
        "/api/v1/auth/register",
        json={"email": "x@example.com", "password": "short"},
    )
    assert r.status_code == 422  # fails min_length validation


def test_admin_requires_superuser(client: TestClient) -> None:
    # No token → 401 (OAuth2 scheme rejects before the route runs).
    assert client.post("/api/v1/admin/ingest/quotes").status_code == 401

    # Authenticated non-superuser → 403.
    _register(client)
    token = _token(client)
    r = client.post(
        "/api/v1/admin/ingest/quotes", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 403
