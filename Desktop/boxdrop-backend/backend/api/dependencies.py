"""Shared FastAPI dependencies."""

from typing import Optional

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.services.auth_service import InvalidTokenError, decode_access_token

# auto_error=False so a missing header raises OUR InvalidTokenError (mapped
# to a clean {"error": {...}} 401 in main.py) instead of FastAPI's default
# bare 403 - keeps every auth failure going through the same error envelope.
_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme)) -> str:
    """Resolves the authenticated username from the `Authorization: Bearer <token>` header."""
    if credentials is None:
        raise InvalidTokenError("Missing Authorization header - please log in.")
    return decode_access_token(credentials.credentials)
