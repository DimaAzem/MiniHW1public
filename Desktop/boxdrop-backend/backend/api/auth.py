"""
Authentication routes: registration and login.

Login now returns a signed JWT session token (not just a username echo) -
the frontend attaches it as `Authorization: Bearer <token>` on every
subsequent request to the packages/routing/analytics routers.
"""

import re
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field, field_validator
from pymongo.errors import DuplicateKeyError

from backend.database.connection import get_database
from backend.services.auth_service import create_access_token, hash_password, verify_password

router = APIRouter()

_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


class UsernameTakenError(Exception):
    def __init__(self, username: str) -> None:
        self.username = username
        super().__init__(f"Username '{username}' is already taken")


class InvalidCredentialsError(Exception):
    def __init__(self) -> None:
        super().__init__("Invalid username or password")


class UserRegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, examples=["dima_a"])
    password: str = Field(..., min_length=8, examples=["SuperSecret123"])

    @field_validator("username")
    @classmethod
    def _username_is_simple(cls, value: str) -> str:
        if not _USERNAME_PATTERN.match(value):
            raise ValueError("Username may only contain letters, numbers, dots, dashes, and underscores.")
        return value


class UserRegisterResponse(BaseModel):
    username: str
    created_at: datetime


class UserLoginRequest(BaseModel):
    username: str
    password: str


class UserLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


@router.post(
    "/auth/register",
    response_model=UserRegisterResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["auth"],
    summary="Register a new BoxDrop user",
)
async def register_user(
    payload: UserRegisterRequest, db: AsyncIOMotorDatabase = Depends(get_database)
) -> UserRegisterResponse:
    existing = await db.users.find_one({"username": payload.username})
    if existing is not None:
        raise UsernameTakenError(payload.username)

    document = {
        "_id": str(uuid4()),
        "username": payload.username,
        "password_hash": hash_password(payload.password),
        "created_at": datetime.now(timezone.utc),
    }
    try:
        await db.users.insert_one(document)
    except DuplicateKeyError as exc:
        raise UsernameTakenError(payload.username) from exc

    return UserRegisterResponse(username=document["username"], created_at=document["created_at"])


@router.post(
    "/auth/login",
    response_model=UserLoginResponse,
    tags=["auth"],
    summary="Log in and receive a session token",
)
async def login_user(payload: UserLoginRequest, db: AsyncIOMotorDatabase = Depends(get_database)) -> UserLoginResponse:
    document = await db.users.find_one({"username": payload.username})
    # Same generic error whether the username doesn't exist or the password
    # is wrong - never let a login endpoint reveal which one it was.
    if document is None or not verify_password(payload.password, document["password_hash"]):
        raise InvalidCredentialsError()

    token = create_access_token(document["username"])
    return UserLoginResponse(access_token=token, username=document["username"])
