"""Security listing and lookup endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Pagination, pagination_params
from app.db.session import get_db
from app.models.enums import AssetClass
from app.models.market import Security
from app.schemas.common import Page
from app.schemas.market import SecurityOut

router = APIRouter(prefix="/securities", tags=["securities"])


@router.get("", response_model=Page[SecurityOut], summary="List securities")
def list_securities(
    db: Session = Depends(get_db),
    pagination: Pagination = Depends(pagination_params),
    asset_class: AssetClass | None = Query(None),
    search: str | None = Query(None, description="Match symbol or name"),
) -> Page[SecurityOut]:
    stmt = select(Security).where(Security.is_active.is_(True))
    if asset_class is not None:
        stmt = stmt.where(Security.asset_class == asset_class)
    if search:
        term = f"%{search.strip()}%"
        stmt = stmt.where(Security.symbol.ilike(term) | Security.name.ilike(term))

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(Security.symbol).offset(pagination.offset).limit(pagination.limit)
    ).all()

    return Page[SecurityOut](
        items=[SecurityOut.model_validate(r) for r in rows],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get(
    "/{provider_symbol}",
    response_model=SecurityOut,
    summary="Get a single security by provider symbol",
)
def get_security(provider_symbol: str, db: Session = Depends(get_db)) -> Security:
    security = db.scalar(
        select(Security).where(Security.provider_symbol == provider_symbol)
    )
    if security is None:
        raise HTTPException(status_code=404, detail="Security not found")
    return security
