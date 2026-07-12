from fastapi import Depends, HTTPException

from ..auth.security import get_current_user
from ..crypto.keys import key_manager
from ..models.auth import User


def require_unlocked(user: User = Depends(get_current_user)) -> User:
    """Sensitive data routes need both a session and an unlocked keyring."""
    if not key_manager.unlocked:
        raise HTTPException(423, "Encryption keyring is locked. POST /auth/unlock first.")
    return user
