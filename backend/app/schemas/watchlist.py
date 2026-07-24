"""Watchlist schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class WatchlistCreate(BaseModel):
    name: str


class WatchlistItemCreate(BaseModel):
    provider_symbol: str


class WatchlistItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    security_id: int


class WatchlistOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    items: list[WatchlistItemOut] = []
