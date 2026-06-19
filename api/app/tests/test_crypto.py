"""Round-trip + tamper tests for the portal-credential encryption helper.

Runs where app deps are installed (the api/worker image), like test_health.
"""
from __future__ import annotations

from app.services.crypto import decrypt, encrypt


def test_encrypt_round_trip():
    secret = "Sup3r-s3cret P@ss / with spaces"
    token = encrypt(secret)
    assert token != secret  # actually encrypted
    assert decrypt(token) == secret


def test_decrypt_garbage_returns_empty():
    # A rotated key / corrupted value must not raise — callers treat "" as
    # "no usable credential".
    assert decrypt("not-a-valid-fernet-token") == ""


def test_tokens_are_nondeterministic():
    # Fernet embeds a random IV, so the same plaintext encrypts differently.
    assert encrypt("same") != encrypt("same")
