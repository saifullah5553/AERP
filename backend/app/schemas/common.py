"""Shared response envelopes."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """A paginated result set."""

    items: list[T]
    total: int = Field(description="Total rows matching the query, ignoring pagination")
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)

    @property
    def pages(self) -> int:
        if self.page_size == 0:
            return 0
        return (self.total + self.page_size - 1) // self.page_size


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    database: str
    redis: str
