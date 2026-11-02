from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.db import get_db
from ...core.models import User
from ...core.security import create_token, current_user, decode_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    role: str
    display_name: str


@router.post("/login", response_model=Token)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    u = db.query(User).filter_by(username=form.username, active=True).first()
    if not u or not verify_password(form.password, u.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "wrong username or password")
    s = get_settings()
    return Token(access_token=create_token(u), refresh_token=create_token(u, minutes=s.refresh_days * 1440, kind="refresh"),
                 role=u.role, display_name=u.display_name)


class Refresh(BaseModel):
    refresh_token: str


@router.post("/refresh", response_model=Token)
def refresh(body: Refresh, db: Session = Depends(get_db)):
    data = decode_token(body.refresh_token)
    if data.get("kind") != "refresh":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "refresh token required")
    u = db.query(User).filter_by(username=data["sub"], active=True).first()
    if not u:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown user")
    s = get_settings()
    return Token(access_token=create_token(u), refresh_token=create_token(u, minutes=s.refresh_days * 1440, kind="refresh"),
                 role=u.role, display_name=u.display_name)


@router.get("/me")
def me(u: User = Depends(current_user)):
    return {"username": u.username, "role": u.role, "display_name": u.display_name}
