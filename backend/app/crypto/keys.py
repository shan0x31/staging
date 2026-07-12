"""Envelope encryption for sensitive fields.

Scheme:
  passphrase --Argon2id--> master key (never stored)
  master key --AES-256-GCM--> wraps a random 32-byte data-encryption key (DEK)
  DEK --AES-256-GCM--> encrypts sensitive column values (per-value nonce)

Only the Argon2id salt, KDF parameters, and the *wrapped* DEK are persisted
(`keyring` table). Rotating the passphrase re-wraps the DEK without touching
data rows. A database or backup stolen without the passphrase is unreadable.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
from datetime import datetime, timezone

from argon2.low_level import Type, hash_secret_raw
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from ..db import Base

_NONCE_LEN = 12
_KEY_LEN = 32

# Argon2id parameters (RFC 9106 second recommended profile: 64 MiB, t=3).
_KDF_PARAMS = {"time_cost": 3, "memory_cost": 64 * 1024, "parallelism": 4}


class KeyringEntry(Base):
    __tablename__ = "keyring"

    id: Mapped[int] = mapped_column(primary_key=True)
    kdf_salt_b64: Mapped[str] = mapped_column(String(64))
    kdf_params_json: Mapped[str] = mapped_column(Text)
    wrapped_dek_b64: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))


class KeyringLockedError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Encryption keyring is locked. Unlock with the passphrase first.")


class WrongPassphraseError(ValueError):
    def __init__(self) -> None:
        super().__init__("Passphrase does not unlock the keyring.")


def _derive_master_key(passphrase: str, salt: bytes, params: dict) -> bytes:
    return hash_secret_raw(
        secret=passphrase.encode(),
        salt=salt,
        time_cost=params["time_cost"],
        memory_cost=params["memory_cost"],
        parallelism=params["parallelism"],
        hash_len=_KEY_LEN,
        type=Type.ID,
    )


class KeyManager:
    """Holds the unwrapped DEK in memory while unlocked. Process-wide singleton
    (SQLAlchemy TypeDecorators run outside request context and need global access)."""

    def __init__(self) -> None:
        self._dek: bytes | None = None

    # -- state ---------------------------------------------------------------

    @property
    def unlocked(self) -> bool:
        return self._dek is not None

    def lock(self) -> None:
        self._dek = None

    def is_initialized(self, db: Session) -> bool:
        return db.execute(select(KeyringEntry.id)).first() is not None

    # -- lifecycle -----------------------------------------------------------

    def initialize(self, db: Session, passphrase: str) -> None:
        if self.is_initialized(db):
            raise ValueError("Keyring already initialized")
        if len(passphrase) < 8:
            raise ValueError("Passphrase must be at least 8 characters")
        salt = secrets.token_bytes(16)
        master = _derive_master_key(passphrase, salt, _KDF_PARAMS)
        dek = secrets.token_bytes(_KEY_LEN)
        nonce = secrets.token_bytes(_NONCE_LEN)
        wrapped = nonce + AESGCM(master).encrypt(nonce, dek, b"pf-dek-v1")
        db.add(KeyringEntry(
            kdf_salt_b64=base64.b64encode(salt).decode(),
            kdf_params_json=json.dumps(_KDF_PARAMS),
            wrapped_dek_b64=base64.b64encode(wrapped).decode(),
        ))
        db.commit()
        self._dek = dek

    def unlock(self, db: Session, passphrase: str) -> None:
        entry = db.execute(select(KeyringEntry)).scalars().first()
        if entry is None:
            raise ValueError("Keyring not initialized")
        salt = base64.b64decode(entry.kdf_salt_b64)
        params = json.loads(entry.kdf_params_json)
        master = _derive_master_key(passphrase, salt, params)
        wrapped = base64.b64decode(entry.wrapped_dek_b64)
        nonce, ct = wrapped[:_NONCE_LEN], wrapped[_NONCE_LEN:]
        try:
            self._dek = AESGCM(master).decrypt(nonce, ct, b"pf-dek-v1")
        except InvalidTag:
            raise WrongPassphraseError() from None

    def rotate_passphrase(self, db: Session, old: str, new: str) -> None:
        self.unlock(db, old)  # proves old passphrase; loads DEK
        if len(new) < 8:
            raise ValueError("Passphrase must be at least 8 characters")
        entry = db.execute(select(KeyringEntry)).scalars().first()
        salt = secrets.token_bytes(16)
        master = _derive_master_key(new, salt, _KDF_PARAMS)
        nonce = secrets.token_bytes(_NONCE_LEN)
        assert self._dek is not None
        entry.kdf_salt_b64 = base64.b64encode(salt).decode()
        entry.kdf_params_json = json.dumps(_KDF_PARAMS)
        entry.wrapped_dek_b64 = base64.b64encode(
            nonce + AESGCM(master).encrypt(nonce, self._dek, b"pf-dek-v1")
        ).decode()
        db.commit()

    # -- data ops ------------------------------------------------------------

    def encrypt(self, plaintext: bytes) -> str:
        if self._dek is None:
            raise KeyringLockedError()
        nonce = secrets.token_bytes(_NONCE_LEN)
        ct = AESGCM(self._dek).encrypt(nonce, plaintext, None)
        return "enc1:" + base64.b64encode(nonce + ct).decode()

    def decrypt(self, token: str) -> bytes:
        if self._dek is None:
            raise KeyringLockedError()
        if not token.startswith("enc1:"):
            raise ValueError("Not an encrypted token")
        raw = base64.b64decode(token[5:])
        nonce, ct = raw[:_NONCE_LEN], raw[_NONCE_LEN:]
        return AESGCM(self._dek).decrypt(nonce, ct, None)

    def encrypt_str(self, value: str) -> str:
        return self.encrypt(value.encode())

    def decrypt_str(self, token: str) -> str:
        return self.decrypt(token).decode()


key_manager = KeyManager()
