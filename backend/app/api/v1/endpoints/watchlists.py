"""Watchlist endpoints (authenticated).

Demonstrates the auth layer end-to-end and exercises the User/Watchlist tables.
All routes are scoped to the current user; a user can never see or mutate another
user's watchlists.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.market import Security
from app.models.user import User, Watchlist, WatchlistItem
from app.schemas.watchlist import WatchlistCreate, WatchlistItemCreate, WatchlistOut

router = APIRouter(prefix="/watchlists", tags=["watchlists"])


def _owned(db: Session, user: User, watchlist_id: int) -> Watchlist:
    wl = db.scalar(
        select(Watchlist)
        .options(selectinload(Watchlist.items))
        .where(Watchlist.id == watchlist_id, Watchlist.user_id == user.id)
    )
    if wl is None:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    return wl


@router.get("", response_model=list[WatchlistOut])
def list_watchlists(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[Watchlist]:
    return list(
        db.scalars(
            select(Watchlist)
            .options(selectinload(Watchlist.items))
            .where(Watchlist.user_id == user.id)
            .order_by(Watchlist.id)
        ).all()
    )


@router.post("", response_model=WatchlistOut, status_code=status.HTTP_201_CREATED)
def create_watchlist(
    payload: WatchlistCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Watchlist:
    wl = Watchlist(user_id=user.id, name=payload.name)
    db.add(wl)
    db.commit()
    db.refresh(wl)
    return wl


@router.post("/{watchlist_id}/items", response_model=WatchlistOut)
def add_item(
    watchlist_id: int,
    payload: WatchlistItemCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Watchlist:
    wl = _owned(db, user, watchlist_id)
    security = db.scalar(
        select(Security).where(Security.provider_symbol == payload.provider_symbol)
    )
    if security is None:
        raise HTTPException(status_code=404, detail="Security not found")
    exists = any(i.security_id == security.id for i in wl.items)
    if not exists:
        db.add(WatchlistItem(watchlist_id=wl.id, security_id=security.id))
        db.commit()
        db.refresh(wl)
    return wl


@router.delete("/{watchlist_id}/items/{security_id}")
def remove_item(
    watchlist_id: int,
    security_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, bool]:
    wl = _owned(db, user, watchlist_id)
    item = next((i for i in wl.items if i.security_id == security_id), None)
    if item is not None:
        db.delete(item)
        db.commit()
    return {"removed": item is not None}
