"""
Stress tests: concurrent request handling under load, and the rate-limiting
middleware's 429 behavior when a client genuinely exceeds its budget.
"""

import asyncio
import time

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.middleware.rate_limit import RateLimitMiddleware


@pytest.mark.asyncio
async def test_many_concurrent_requests_are_all_handled_correctly(authed_client):
    """
    Fires 50 concurrent requests at a protected endpoint through the async
    server and confirms every single one succeeds within a sane time budget -
    demonstrating the async/await backend genuinely handles concurrency
    rather than serializing (or dropping) requests under load.
    """
    client, headers = authed_client

    async def _list_packages():
        return await client.get("/api/packages", headers=headers)

    start = time.monotonic()
    responses = await asyncio.gather(*[_list_packages() for _ in range(50)])
    elapsed = time.monotonic() - start

    assert all(response.status_code == 200 for response in responses)
    assert elapsed < 5.0, f"50 concurrent requests took {elapsed:.2f}s - too slow for an async backend"


def _build_rate_limited_test_app(max_requests: int, window_seconds: float) -> FastAPI:
    """
    A minimal standalone app wrapping ONLY the rate limiter, isolated from
    the real app's shared middleware state. The real app uses a much more
    generous limit (300 req/10s) specifically so normal test-suite traffic
    across every other test in this session never trips it; this test
    exercises the limiter's actual 429 behavior deterministically instead.
    """
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, max_requests=max_requests, window_seconds=window_seconds)

    @app.get("/ping")
    async def ping() -> dict:
        return {"ok": True}

    return app


@pytest.mark.asyncio
async def test_rate_limit_middleware_returns_429_once_exceeded():
    app = _build_rate_limited_test_app(max_requests=5, window_seconds=2.0)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://ratelimit-test") as ac:
        responses = [await ac.get("/ping") for _ in range(8)]

    statuses = [response.status_code for response in responses]
    assert statuses[:5] == [200] * 5
    assert 429 in statuses[5:]

    limited_response = next(response for response in responses if response.status_code == 429)
    assert limited_response.json()["error"]["code"] == "RATE_LIMITED"


@pytest.mark.asyncio
async def test_rate_limit_exempts_health_check():
    """The health endpoint must never be throttled - docker-compose polls it every 10s."""
    app = _build_rate_limited_test_app(max_requests=2, window_seconds=10.0)

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "healthy"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://ratelimit-test") as ac:
        statuses = [(await ac.get("/api/health")).status_code for _ in range(10)]

    assert all(status_code == 200 for status_code in statuses)
