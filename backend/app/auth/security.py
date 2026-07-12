from __future__ import annotations

import hashlib
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models.auth import SessionToken, User, utcnow

_ph = PasswordHasher()  # argon2id defaults
_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        _ph.verify(password_hash, password)
        return True
    except VerifyMismatchError:
        return False


# -- login rate limiting (in-memory sliding window) ---------------------------

_attempts: dict[str, deque[float]] = defaultdict(deque)
_MAX_ATTEMPTS = 8
_WINDOW_SEC = 300


def check_rate_limit(key: str) -> None:
    now = time.monotonic()
    window = _attempts[key]
    while window and now - window[0] > _WINDOW_SEC:
        window.popleft()
    if len(window) >= _MAX_ATTEMPTS:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "Too many login attempts; try again later.")
    window.append(now)


def clear_rate_limit(key: str) -> None:
    _attempts.pop(key, None)


# -- sessions -----------------------------------------------------------------

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    db.add(SessionToken(
        token_hash=_hash_token(token),
        user_id=user.id,
        expires_at=utcnow() + timedelta(hours=settings.session_ttl_hours),
    ))
    db.commit()
    return token


def revoke_session(db: Session, token: str) -> None:
    row = db.execute(
        select(SessionToken).where(SessionToken.token_hash == _hash_token(token))
    ).scalars().first()
    if row:
        db.delete(row)
        db.commit()


def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    row = db.execute(
        select(SessionToken).where(SessionToken.token_hash == _hash_token(creds.credentials))
    ).scalars().first()
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session")
    expires = row.expires_at
    if expires.tzinfo is None:  # SQLite drops tzinfo
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        db.delete(row)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    user = db.get(User, row.user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session")
    return user
