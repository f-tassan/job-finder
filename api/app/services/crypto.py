"""Symmetric encryption for secrets at rest (portal credentials).

Portal passwords are the user's own logins to employer ATS sites. They must be
recoverable (we type them back to log in), so they're encrypted, not hashed.
Fernet (AES-128-CBC + HMAC) from `cryptography` gives authenticated symmetric
encryption with a single key.

The key comes from `settings.credentials_key` (a real Fernet key). If unset we
derive one from `jwt_secret` so dev/local works out of the box — but a dedicated
`CREDENTIALS_KEY` should be set in production, and rotating it invalidates every
stored credential.
"""
from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


@lru_cache
def _fernet() -> Fernet:
    key = settings.credentials_key
    if key:
        return Fernet(key.encode() if isinstance(key, str) else key)
    # Derive a stable 32-byte urlsafe key from the app secret.
    digest = hashlib.sha256(settings.jwt_secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Return the plaintext, or "" if the token can't be decrypted (e.g. the
    key was rotated). Callers treat "" as "no usable credential"."""
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, ValueError):
        return ""
