"""
Authentication service: password hashing and JWT session tokens.

Two independent concerns:
- Passwords are hashed one-way with bcrypt. Even we can't recover them.
- Login issues a signed JWT (HS256) that the frontend attaches as a Bearer
  token on every subsequent request. Unlike the app-password encryption this
  project used to have, a JWT secret rotating has no data-loss consequence -
  it just forces everyone to log in again - so a simple env-var-with-a-dev-
  fallback is appropriate here (no key-persistence machinery needed).
"""

import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

# NEVER use this fallback in a real deployment - set JWT_SECRET_KEY yourself.
# Unlike a data-encryption key, losing/rotating this only forces re-login,
# so a hardcoded dev default (clearly marked) is an acceptable tradeoff here.
# `or` (not a plain os.getenv default) so an empty-but-present env var - e.g.
# docker-compose's ${JWT_SECRET_KEY:-} substitution when nothing is set in
# .env - falls back too, not just a fully-unset variable.
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY") or "dev-insecure-secret-change-in-production"
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24


class InvalidTokenError(Exception):
    """Raised for a missing, malformed, expired, or otherwise untrustworthy token."""


def hash_password(plain_password: str) -> str:
    """One-way bcrypt hash for the BoxDrop login password."""
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # Malformed hash (shouldn't happen with our own data, but never trust stored state blindly).
        return False


def create_access_token(username: str) -> str:
    """Issues a signed, time-limited JWT identifying `username` (the `sub` claim)."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "iat": now,
        "exp": now + timedelta(hours=JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> str:
    """Verifies a JWT and returns the username it identifies, or raises InvalidTokenError."""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise InvalidTokenError("Session expired - please log in again.") from exc
    except jwt.InvalidTokenError as exc:
        raise InvalidTokenError("Invalid or malformed session token.") from exc

    username = payload.get("sub")
    if not username:
        raise InvalidTokenError("Session token is missing its subject claim.")
    return username
