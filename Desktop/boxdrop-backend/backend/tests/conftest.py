"""
Shared pytest fixtures for the backend test suite.

Every test exercises the REAL FastAPI app and REAL bcrypt/JWT logic against
an in-memory `mongomock_motor` database - only the MongoDB storage layer is
swapped for a compatible in-memory equivalent, so no business logic is
mocked and no live MongoDB instance is needed to run `pytest`.
"""

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from backend.database import connection as db_connection
from backend.main import app


@pytest_asyncio.fixture
async def client():
    """A plain (unauthenticated) AsyncClient wired to the real app with a mocked database."""
    mock_mongo_client = AsyncMongoMockClient()
    mock_db = mock_mongo_client["boxdrop_test_db"]
    await mock_db.users.create_index("username", unique=True)
    await mock_db.packages.create_index([("user_id", 1), ("tracking_number", 1)], unique=True)

    db_connection.mongo_manager._client = mock_mongo_client
    db_connection.mongo_manager._db = mock_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    db_connection.mongo_manager._client = None
    db_connection.mongo_manager._db = None


@pytest_asyncio.fixture
async def authed_client(client: AsyncClient):
    """
    Registers and logs in a throwaway user, returning (client, auth_headers)
    so every protected-route test can skip the register/login boilerplate.
    """
    username = "test_user_1"
    password = "TestPassword123"
    await client.post("/api/auth/register", json={"username": username, "password": password})
    login_response = await client.post("/api/auth/login", json={"username": username, "password": password})
    token = login_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    return client, headers


@pytest_asyncio.fixture
async def second_authed_client(client: AsyncClient):
    """A second, independent user on the SAME app/database - for cross-user isolation tests."""
    username = "test_user_2"
    password = "TestPassword456"
    await client.post("/api/auth/register", json={"username": username, "password": password})
    login_response = await client.post("/api/auth/login", json={"username": username, "password": password})
    token = login_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    return client, headers
