"""Authentication (JWT) and role-based authorisation. Production replaces the local user table with OIDC/SSO."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import AuditLog, User

pwd = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
oauth2 = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

ROLES = ("supervisor", "technician", "manager", "admin")


def hash_password(p: str) -> str:
    return pwd.hash(p)


def verify_password(p: str, h: str) -> bool:
    return pwd.verify(p, h)


def create_token(user: User, minutes: int | None = None, kind: str = "access") -> str:
    s = get_settings()
    exp = datetime.utcnow() + timedelta(minutes=minutes or s.jwt_minutes)
    return jwt.encode({"sub": user.username, "role": user.role, "kind": kind, "exp": exp}, s.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    except JWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token")


def current_user(token: str = Depends(oauth2), db: Session = Depends(get_db)) -> User:
    data = decode_token(token)
    if data.get("kind") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "access token required")
    u = db.query(User).filter(User.username == data["sub"], User.active.is_(True)).first()
    if not u:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown user")
    return u


def require(*roles: str):
    allowed: Iterable[str] = roles or ROLES

    def dep(u: User = Depends(current_user)) -> User:
        if u.role not in allowed and u.role != "admin":
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"role {u.role} not allowed")
        return u

    return dep


def audit(db: Session, actor: str, action: str, entity: str, entity_id: str | None, before=None, after=None) -> None:
    db.add(AuditLog(actor=actor, action=action, entity=entity, entity_id=entity_id, before=before, after=after))


def seed_demo_users(db: Session) -> int:
    """Four demo accounts for dev/staging. Disabled when BASEERA_ENV=production."""
    s = get_settings()
    if s.env == "production":
        return 0
    n = 0
    for username, role, name in (("supervisor", "supervisor", "مشرف صيانة الإنارة"), ("technician", "technician", "فني الطاقم"),
                                 ("manager", "manager", "مدير التشغيل"), ("admin", "admin", "مدير النظام")):
        if not db.query(User).filter_by(username=username).first():
            db.add(User(username=username, password_hash=hash_password(s.demo_password), role=role, display_name=name))
            n += 1
    db.commit()
    return n
