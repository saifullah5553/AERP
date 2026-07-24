"""Auth request/response schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class UserCreate(BaseModel):
    # A permissive email check keeps the dependency footprint minimal (no
    # email-validator); real MX/format validation can be added later.
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=320)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str | None
    is_active: bool
    is_superuser: bool


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
