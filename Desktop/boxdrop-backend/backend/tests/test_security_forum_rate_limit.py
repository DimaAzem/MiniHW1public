"""
Security/throttling test: the forum's own route-specific rate limiter,
distinct from the single global budget in backend/middleware/rate_limit.py.
"""

import pytest

from backend.api import forum as forum_module


@pytest.fixture(autouse=True)
def _reset_forum_rate_limit_state():
    """
    The forum limiter's counters are module-level and shared across the
    whole test session - reset them before/after every test in this file so
    tests can't bleed into each other's budget.
    """
    forum_module._forum_post_hits.clear()
    yield
    forum_module._forum_post_hits.clear()


@pytest.mark.asyncio
async def test_forum_posting_past_the_limit_returns_429(authed_client):
    client, headers = authed_client
    statuses = []
    for i in range(forum_module.FORUM_POST_LIMIT + 2):
        response = await client.post(
            "/api/forum/posts", json={"content": f"Post {i}", "anonymous": False}, headers=headers
        )
        statuses.append(response.status_code)

    assert statuses[: forum_module.FORUM_POST_LIMIT] == [201] * forum_module.FORUM_POST_LIMIT
    assert 429 in statuses[forum_module.FORUM_POST_LIMIT :]


@pytest.mark.asyncio
async def test_forum_rate_limited_response_uses_the_standard_error_envelope(authed_client):
    client, headers = authed_client
    for i in range(forum_module.FORUM_POST_LIMIT):
        await client.post("/api/forum/posts", json={"content": f"Post {i}", "anonymous": False}, headers=headers)

    limited = await client.post("/api/forum/posts", json={"content": "one too many"}, headers=headers)
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "FORUM_RATE_LIMITED"


@pytest.mark.asyncio
async def test_forum_rate_limit_is_per_user_not_global(authed_client, second_authed_client):
    client_a, headers_a = authed_client
    client_b, headers_b = second_authed_client

    for i in range(forum_module.FORUM_POST_LIMIT):
        await client_a.post("/api/forum/posts", json={"content": f"A {i}", "anonymous": False}, headers=headers_a)
    limited = await client_a.post("/api/forum/posts", json={"content": "one too many"}, headers=headers_a)
    assert limited.status_code == 429

    # User B's budget is completely separate.
    fresh = await client_b.post(
        "/api/forum/posts", json={"content": "B's first post", "anonymous": False}, headers=headers_b
    )
    assert fresh.status_code == 201
