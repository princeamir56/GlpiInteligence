"""Authentication & authorization: JWT create/verify, bcrypt hashing, role deps.

Roles: DSI, MANAGER, DIRECTION. Endpoints declare access with
`Depends(require_role("DSI", "MANAGER"))`. Tokens carry `sub` (username), `role`,
and `type` ("access" | "refresh").
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .database import get_session

ROLES = ("DSI", "MANAGER", "DIRECTION")
TokenType = Literal["access", "refresh"]

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=True)


class CurrentUser(BaseModel):
    user_id: int
    username: str
    role: str


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def _create_token(sub: str, role: str, token_type: TokenType, ttl: timedelta) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "role": role,
        "type": token_type,
        "iat": now,
        "exp": now + ttl,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(sub: str, role: str) -> str:
    s = get_settings()
    return _create_token(sub, role, "access", timedelta(minutes=s.access_token_ttl_min))


def create_refresh_token(sub: str, role: str) -> str:
    s = get_settings()
    return _create_token(sub, role, "refresh", timedelta(days=s.refresh_token_ttl_days))


def decode_token(token: str) -> dict:
    settings = get_settings()
    try:
        return jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def authenticate_user(
    session: AsyncSession, username: str, password: str
) -> CurrentUser | None:
    row = (
        await session.execute(
            text(
                "SELECT id, username, password_hash, role "
                "FROM api_users WHERE username = :u"
            ),
            {"u": username},
        )
    ).first()
    if row is None:
        return None
    if not verify_password(password, row.password_hash):
        return None
    return CurrentUser(user_id=row.id, username=row.username, role=row.role)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_session),
) -> CurrentUser:
    payload = decode_token(token)
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not an access token",
        )
    username = payload.get("sub")
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token"
        )
    row = (
        await session.execute(
            text("SELECT id, username, role FROM api_users WHERE username = :u"),
            {"u": username},
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User no longer exists"
        )
    return CurrentUser(user_id=row.id, username=row.username, role=row.role)


def require_role(*allowed: str):
    """Dependency factory: 403 unless the current user has one of `allowed` roles."""

    async def _dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {', '.join(allowed)}",
            )
        return user

    return _dep
