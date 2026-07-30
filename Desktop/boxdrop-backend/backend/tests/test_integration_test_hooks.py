"""
Integration tests: the ENABLE_TEST_ENDPOINTS-gated test hooks.

The default test session runs with the flag unset, so conftest.py's `app`
(and its `client` fixture) never has the test-hooks router registered at
all - the first test below confirms that directly. The second test reloads
backend.main under the flag set via monkeypatch and builds a fresh app
instance to confirm the hooks work when explicitly enabled, without
affecting the already-imported `app` other test files use (Python binds
`from backend.main import app` to the object that existed at import time -
a later reload of the module doesn't retroactively change that binding).
"""

import importlib

import pytest
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from backend.database import connection as db_connection


@pytest.mark.asyncio
async def test_test_hooks_are_absent_by_default(client):
    response = await client.post("/api/test/seed-mock-data")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_test_hooks_exist_when_flag_enabled(monkeypatch):
    monkeypatch.setenv("ENABLE_TEST_ENDPOINTS", "true")
    import backend.main as main_module

    reloaded_main = importlib.reload(main_module)

    mock_mongo_client = AsyncMongoMockClient()
    mock_db = mock_mongo_client["boxdrop_test_hooks_db"]
    db_connection.mongo_manager._client = mock_mongo_client
    db_connection.mongo_manager._db = mock_db

    try:
        transport = ASGITransport(app=reloaded_main.app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            seed_response = await ac.post("/api/test/seed-mock-data")
            assert seed_response.status_code == 200
            assert seed_response.json()["seeded"] is True

            inject_response = await ac.post(
                "/api/test/inject-delay-event",
                json={
                    "user_id": "demo_user",
                    "tracking_number": "TRK-INJECTED",
                    "delay_probability": 0.9,
                    "risk_level": "high",
                },
            )
            assert inject_response.status_code == 201

            reset_response = await ac.delete("/api/test/reset")
            assert reset_response.status_code == 200
            assert "packages" in reset_response.json()["collections_cleared"]
    finally:
        db_connection.mongo_manager._client = None
        db_connection.mongo_manager._db = None
        monkeypatch.delenv("ENABLE_TEST_ENDPOINTS", raising=False)
        importlib.reload(main_module)
