"""SQLAlchemy column types that transparently encrypt values with the DEK.

Values are AES-256-GCM tokens on disk; Python code sees plain str/Decimal/dict.
Consequence: encrypted columns cannot be filtered or aggregated in SQL — load
and compute in the application layer (fine at single-user scale).
"""
from __future__ import annotations

import json
from decimal import Decimal

from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from .keys import key_manager


class EncryptedStr(TypeDecorator):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return key_manager.encrypt_str(str(value))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return key_manager.decrypt_str(value)


class EncryptedDecimal(TypeDecorator):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return key_manager.encrypt_str(str(Decimal(value)))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return Decimal(key_manager.decrypt_str(value))


class EncryptedJSON(TypeDecorator):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return key_manager.encrypt_str(json.dumps(value, default=str))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return json.loads(key_manager.decrypt_str(value))
