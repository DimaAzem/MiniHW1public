"""
Integration tests: the real-time forum's WebSocket endpoint.

httpx.AsyncClient can't open WebSocket connections, so this file uses
Starlette's synchronous TestClient specifically for the WS handshake and
broadcast test - everything else in this suite uses the async client from
conftest.py. TestClient's `with` context normally triggers the app's real
lifespan (which would try to connect to a real MongoDB); connect()/close()
are stubbed out for the duration since the mongomock database is already
wired up manually, exactly mirroring what conftest.py's async `client`
fixture does implicitly by never triggering the lifespan at all.
"""

import asyncio
from unittest.mock import patch

import pytest
from mongomock_motor import AsyncMongoMockClient
from starlette.testclient import TestClient

from backend.database import connection as db_connection
from backend.main import app


@pytest.fixture
def ws_client():
    mock_mongo_client = AsyncMongoMockClient()
    mock_db = mock_mongo_client["boxdrop_test_ws_db"]
    asyncio.run(mock_db.users.create_index("username", unique=True))

    db_connection.mongo_manager._client = mock_mongo_client
    db_connection.mongo_manager._db = mock_db

    async def _noop_connect() -> None:
        pass  # mongomock already wired above; skip the real connect/retry dance

    async def _noop_close() -> None:
        pass  # keep the mock db alive across the TestClient's lifespan shutdown

    with patch.object(db_connection.mongo_manager, "connect", _noop_connect), patch.object(
        db_connection.mongo_manager, "close", _noop_close
    ):
        with TestClient(app) as test_client:
            yield test_client

    db_connection.mongo_manager._client = None
    db_connection.mongo_manager._db = None


def _register_and_login(test_client: TestClient, username: str, password: str) -> str:
    test_client.post("/api/auth/register", json={"username": username, "password": password})
    response = test_client.post("/api/auth/login", json={"username": username, "password": password})
    return response.json()["access_token"]


def test_websocket_rejects_an_invalid_token(ws_client: TestClient):
    with pytest.raises(Exception):
        with ws_client.websocket_connect("/api/forum/ws?token=not-a-real-token") as websocket:
            websocket.receive_text()


def test_websocket_receives_broadcast_on_new_post(ws_client: TestClient):
    token = _register_and_login(ws_client, "ws_user", "WsPassword123")

    with ws_client.websocket_connect(f"/api/forum/ws?token={token}") as websocket:
        response = ws_client.post(
            "/api/forum/posts",
            json={"content": "Hello forum", "anonymous": False},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 201

        broadcast = websocket.receive_json()
        assert broadcast["content"] == "Hello forum"
        assert broadcast["display_name"] == "ws_user"


def test_websocket_broadcast_respects_anonymity(ws_client: TestClient):
    token = _register_and_login(ws_client, "ws_user_anon", "WsPassword123")

    with ws_client.websocket_connect(f"/api/forum/ws?token={token}") as websocket:
        ws_client.post(
            "/api/forum/posts",
            json={"content": "secret gripe", "anonymous": True},
            headers={"Authorization": f"Bearer {token}"},
        )
        broadcast = websocket.receive_json()
        assert broadcast["display_name"] == "Anonymous"
