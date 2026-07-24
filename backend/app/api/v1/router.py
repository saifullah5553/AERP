"""Aggregate v1 API router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import (
    admin,
    auth,
    company,
    health,
    markets,
    screener,
    securities,
    stream,
    watchlists,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(markets.router)
api_router.include_router(securities.router)
api_router.include_router(screener.router)
api_router.include_router(company.router)
api_router.include_router(stream.router)
api_router.include_router(watchlists.router)
api_router.include_router(admin.router)
