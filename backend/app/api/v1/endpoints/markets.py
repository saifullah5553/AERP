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


@router.get("/meta", summary="Snapshot freshness + coverage metadata")
def market_meta(db: Session = Depends(get_db)) -> dict:
    from datetime import UTC, datetime

    from sqlalchemy import func

    from app.models.market import Security

    total = db.scalar(select(func.count()).select_from(Security)) or 0
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "securities": total,
        "mode": "live",
    }


@router.get("/pulse", summary="Bullish/bearish/neutral pulse per market")
def market_pulse(db: Session = Depends(get_db)) -> list[dict]:
    return compute_pulse(db)


@router.get("/sectors", summary="Sector rotation + sector-average stats per region")
def market_sectors(db: Session = Depends(get_db)) -> dict:
    from app.services.sectors import build_sector_stats

    return build_sector_stats(db)


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


@router.get("/swing", summary="Swing/positional opportunity ranking")
def market_swing(db: Session = Depends(get_db)) -> list[dict]:
    from app.ingestion.portfolio360 import Portfolio360Client
    from app.services.macro_regime import build_macro_regime
    from app.services.sectors import build_sector_stats
    from app.services.swing import build_swing

    pk = None
    try:
        pk = Portfolio360Client().pk_macro()
    except Exception:  # noqa: BLE001 - network optional
        pk = None
    regime = build_macro_regime(db, pk)
    return build_swing(db, build_sector_stats(db), regime, None)["ranked"]
