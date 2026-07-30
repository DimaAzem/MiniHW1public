"""
Unit tests: password hashing and JWT session tokens, in isolation - no HTTP,
no database, just the pure functions in backend/services/auth_service.py.
"""

import pytest

from backend.services.auth_service import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_hash_password_produces_a_bcrypt_hash_not_plaintext():
    hashed = hash_password("SuperSecret123")
    assert hashed != "SuperSecret123"
    assert hashed.startswith("$2b$")


def test_verify_password_roundtrip():
    hashed = hash_password("SuperSecret123")
    assert verify_password("SuperSecret123", hashed) is True
    assert verify_password("WrongPassword", hashed) is False


def test_hash_password_is_salted_differently_each_time():
    # Two hashes of the same password must differ (bcrypt salts per-call),
    # even though both still verify correctly.
    first = hash_password("SamePassword1")
    second = hash_password("SamePassword1")
    assert first != second
    assert verify_password("SamePassword1", first)
    assert verify_password("SamePassword1", second)


def test_create_and_decode_access_token_roundtrip():
    token = create_access_token("dima_a")
    assert decode_access_token(token) == "dima_a"


def test_decode_access_token_rejects_garbage():
    with pytest.raises(InvalidTokenError):
        decode_access_token("not-a-real-token")


def test_decode_access_token_rejects_a_tampered_token():
    token = create_access_token("dima_a")
    # Flip the last two characters of the signature - token must fail verification.
    tampered = token[:-2] + ("aa" if not token.endswith("aa") else "bb")
    with pytest.raises(InvalidTokenError):
        decode_access_token(tampered)


def test_decode_access_token_rejects_empty_string():
    with pytest.raises(InvalidTokenError):
        decode_access_token("")
