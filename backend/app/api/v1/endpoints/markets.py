"""Market reference endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.market import Market
from app.schemas.market import MarketOut
from app.services.pulse import compute_pulse

router = APIRouter(prefix="/markets", tags=["markets"])


@router.get("", response_model=list[MarketOut], summary="List all markets")
def list_markets(db: Session = Depends(get_db)) -> list[Market]:
    return list(db.scalars(select(Market).order_by(Market.code)).all())


@router.get("/pulse", summary="Bullish/bearish/neutral pulse per market")
def market_pulse(db: Session = Depends(get_db)) -> list[dict]:
    return compute_pulse(db)


@router.get("/regime", summary="Per-country macro regime + Market Health Score")
def market_regime(db: Session = Depends(get_db)) -> dict:
    from app.ingestion.portfolio360 import Portfolio360Client
    from app.services.macro_regime import build_macro_regime

    pk = None
    try:
        pk = Portfolio360Client().pk_macro()
    except Exception:  # noqa: BLE001 - network optional
        pk = None
    return build_macro_regime(db, pk)
