from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..crypto.keys import WrongPassphraseError, key_manager
from ..db import get_db
from ..models.auth import AuditLog, User
from .security import (
    check_rate_limit,
    clear_rate_limit,
    create_session,
    get_current_user,
    hash_password,
    revoke_session,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=False)


class SetupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8)
    # Encryption passphrase; may equal the password but rotating one then
    # won't rotate the other. Losing it makes encrypted data unrecoverable.
    encryption_passphrase: str = Field(min_length=8)


class LoginRequest(BaseModel):
    username: str
    password: str


class PassphraseRequest(BaseModel):
    passphrase: str


class StatusResponse(BaseModel):
    setup_complete: bool
    unlocked: bool


@router.get("/status", response_model=StatusResponse)
def auth_status(db: Session = Depends(get_db)) -> StatusResponse:
    has_user = db.execute(select(User.id)).first() is not None
    return StatusResponse(setup_complete=has_user, unlocked=key_manager.unlocked)


@router.post("/setup", status_code=201)
def setup(body: SetupRequest, db: Session = Depends(get_db)) -> dict:
    if db.execute(select(User.id)).first() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Setup already completed")
    key_manager.initialize(db, body.encryption_passphrase)
    user = User(username=body.username, password_hash=hash_password(body.password))
    db.add(user)
    db.add(AuditLog(actor="web", action="auth.setup", detail=f"user={body.username}"))
    db.commit()
    token = create_session(db, user)
    return {"token": token}


@router.post("/login")
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    client = request.client.host if request.client else "unknown"
    check_rate_limit(f"{client}:{body.username}")
    user = db.execute(select(User).where(User.username == body.username)).scalars().first()
    if user is None or not verify_password(body.password, user.password_hash):
        db.add(AuditLog(actor="web", action="auth.login_failed", detail=f"user={body.username}"))
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    clear_rate_limit(f"{client}:{body.username}")
    token = create_session(db, user)
    db.add(AuditLog(actor="web", action="auth.login", detail=f"user={body.username}"))
    db.commit()
    return {"token": token}


@router.post("/logout")
def logout(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    if creds:
        revoke_session(db, creds.credentials)
    return {"ok": True}


@router.post("/unlock")
def unlock(
    body: PassphraseRequest,
    request: Request,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    client = request.client.host if request.client else "unknown"
    check_rate_limit(f"unlock:{client}")
    try:
        key_manager.unlock(db, body.passphrase)
    except WrongPassphraseError:
        db.add(AuditLog(actor="web", action="auth.unlock_failed"))
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong passphrase")
    clear_rate_limit(f"unlock:{client}")
    db.add(AuditLog(actor="web", action="auth.unlock"))
    db.commit()
    return {"ok": True}


@router.post("/lock")
def lock(db: Session = Depends(get_db), _user: User = Depends(get_current_user)) -> dict:
    key_manager.lock()
    db.add(AuditLog(actor="web", action="auth.lock"))
    db.commit()
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(get_current_user)) -> dict:
    return {"username": user.username}
