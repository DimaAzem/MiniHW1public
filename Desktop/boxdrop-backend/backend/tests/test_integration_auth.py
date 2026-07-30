"""
Integration tests: registration and login through the real ASGI app and
real Motor queries against mongomock - the actual HTTP routes end to end,
not the underlying functions in isolation.
"""

import pytest
from httpx import AsyncClient

from backend.database import connection as db_connection

VALID_USER = {"username": "dima_a", "password": "SuperSecret123"}


@pytest.mark.asyncio
async def test_register_creates_a_user_record_in_the_database(client: AsyncClient):
    response = await client.post("/api/auth/register", json=VALID_USER)
    assert response.status_code == 201
    body = response.json()
    assert body["username"] == "dima_a"
    assert "password" not in body
    assert "password_hash" not in body

    stored = await db_connection.mongo_manager.database.users.find_one({"username": "dima_a"})
    assert stored is not None
    assert stored["password_hash"] != VALID_USER["password"]


@pytest.mark.asyncio
async def test_register_duplicate_username_returns_conflict(client: AsyncClient):
    first = await client.post("/api/auth/register", json=VALID_USER)
    assert first.status_code == 201
    second = await client.post("/api/auth/register", json=VALID_USER)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "USERNAME_TAKEN"


@pytest.mark.asyncio
async def test_register_rejects_short_password(client: AsyncClient):
    response = await client.post("/api/auth/register", json={**VALID_USER, "password": "short"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_login_returns_a_usable_bearer_token(client: AsyncClient):
    await client.post("/api/auth/register", json=VALID_USER)
    response = await client.post("/api/auth/login", json=VALID_USER)
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["username"] == "dima_a"

    token = body["access_token"]
    protected = await client.get("/api/packages", headers={"Authorization": f"Bearer {token}"})
    assert protected.status_code == 200


@pytest.mark.asyncio
async def test_login_wrong_password_is_rejected(client: AsyncClient):
    await client.post("/api/auth/register", json=VALID_USER)
    response = await client.post("/api/auth/login", json={"username": "dima_a", "password": "WrongPassword1"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_login_unknown_username_gets_the_same_generic_error(client: AsyncClient):
    response = await client.post("/api/auth/login", json={"username": "nobody_registered", "password": "WhoKnows123"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert response.json()["error"]["message"] == "Invalid username or password"
