"""Client for the Portfolio360 backend (backend.capitalmarketsforall.com).

Free, CORS-gated JSON (needs browser Origin/Referer headers) and reachable from CI —
the richest free source of Pakistan-specific macro, flows, sector rotation and events.
Injectable httpx client so tests run offline. One shared client for all PSX macro/market
feeds we consume (macro now; sector-rotation / investor-flows / events in later phases).
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.core.logging import get_logger

log = get_logger(__name__)

BASE = "https://backend.capitalmarketsforall.com"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AERP/1.0)",
    "Origin": "https://portfolio360.app",
    "Referer": "https://portfolio360.app/",
    "Accept": "application/json",
}


class Portfolio360Client:
    def __init__(self, client: httpx.Client | None = None, timeout: float = 30.0):
        self._client = client or httpx.Client(base_url=BASE, headers=_HEADERS, timeout=timeout)

    def _get(self, path: str, params: dict | None = None) -> Any:
        resp = self._client.get(path, params=params)
        resp.raise_for_status()
        try:
            return resp.json()
        except json.JSONDecodeError:
            return None

    def pk_macro(self) -> dict[str, list[dict[str, Any]]]:
        """Pakistan macro series → {series_key: [{'t': date, 'v': value}, ...]}."""
        data = self._get("/api/macros/pakistan")
        out: dict[str, list[dict[str, Any]]] = {}
        for s in (data or {}).get("series", []):
            key = s.get("key")
            pts = s.get("points") or []
            if key and pts:
                out[key] = pts
        return out

    def pk_index(self, code: str = "KSE100") -> dict[str, Any] | None:
        """Current PSX index level/change (Yahoo has no usable KSE100). Returns
        {name, price, change_pct} or None."""
        data = self._get(f"/api/market/indices/{code}")
        ov = (data or {}).get("overview") if isinstance(data, dict) else None
        if not isinstance(ov, dict) or ov.get("current") is None:
            return None
        return {
            "name": ov.get("name") or code,
            "price": ov.get("current"),
            "change_pct": ov.get("changePercent"),
        }

    def pk_investor_flows(self, sessions: int = 30) -> Any:
        return self._get("/api/market/psx/investor-flows", {"sessions": sessions})

    def pk_sector_rotation(self) -> Any:
        return self._get("/api/market/sector-rotation", {"region": "PK", "window": "3m"})

    def pk_economic_events(self, limit: int = 20) -> list[dict]:
        data = self._get("/api/market/economic-events", {"limit": limit, "country": "PK"})
        return (data or {}).get("events", []) if isinstance(data, dict) else []

    def announcements(self, count: int = 60) -> list[dict]:
        data = self._get("/api/market/announcements", {"count": count})
        return (data or {}).get("items", []) if isinstance(data, dict) else []

    def pk_corporate_actions(self) -> list[dict]:
        data = self._get("/api/inventory/corporate-actions/public", {"exchange": "PSX"})
        return (data or {}).get("items", []) if isinstance(data, dict) else []
