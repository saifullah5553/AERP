"""Company detail endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.company import CompanyDetail
from app.services.company import get_company

router = APIRouter(prefix="/company", tags=["company"])


@router.get(
    "/{provider_symbol}",
    response_model=CompanyDetail,
    summary="Full company detail (profile, scores, statements, patterns, peers, summary)",
)
def company_detail(provider_symbol: str, db: Session = Depends(get_db)) -> CompanyDetail:
    detail = get_company(db, provider_symbol)
    if detail is None:
        raise HTTPException(status_code=404, detail="Security not found")
    return detail
