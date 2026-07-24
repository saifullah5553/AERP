"""Aggregate v1 API router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import admin, company, health, markets, screener, securities

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(markets.router)
api_router.include_router(securities.router)
api_router.include_router(screener.router)
api_router.include_router(company.router)
api_router.include_router(admin.router)
