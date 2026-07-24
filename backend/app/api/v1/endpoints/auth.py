"""Authentication endpoints: register, login (OAuth2 password), me."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import create_access_token
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import Token, UserCreate, UserOut
from app.services.auth import authenticate, create_user, get_by_email

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, db: Session = Depends(get_db)) -> User:
    if get_by_email(db, payload.email) is not None:
        raise HTTPException(status_code=400, detail="Email already registered")
    return create_user(db, payload.email, payload.password, payload.full_name)


@router.post("/login", response_model=Token, summary="OAuth2 password login")
def login(
    form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)
) -> Token:
    user = authenticate(db, form.username, form.password)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(access_token=create_access_token(subject=str(user.id)))


@router.get("/me", response_model=UserOut, summary="Current user")
def me(user: User = Depends(get_current_user)) -> User:
    return user
