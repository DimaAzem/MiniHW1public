"""
Security tests: protected endpoints must reject unauthenticated requests,
and a valid session for one user must never grant access to (or even reveal
the existence of) another user's data - authorization, not just authentication.
"""

from datetime import datetime, timedelta, timezone

import pytest


@pytest.mark.asyncio
async def test_list_packages_requires_authentication(client):
    response = await client.get("/api/packages")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


@pytest.mark.asyncio
async def test_create_package_requires_authentication(client):
    response = await client.post(
        "/api/packages",
        json={
            "tracking_number": "TRK-X",
            "carrier": "DHL",
            "estimated_delivery": datetime.now(timezone.utc).isoformat(),
        },
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_route_optimize_requires_authentication(client):
    response = await client.post("/api/routing/optimize", json={"tracking_numbers": ["TRK-X"]})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_analytics_predict_requires_authentication(client):
    response = await client.post("/api/analytics/predict", json={"carrier": "DHL"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_garbage_bearer_token_is_rejected(client):
    response = await client.get("/api/packages", headers={"Authorization": "Bearer totally-not-a-real-token"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


@pytest.mark.asyncio
async def test_user_cannot_read_another_users_package(authed_client, second_authed_client):
    client_a, headers_a = authed_client
    client_b, headers_b = second_authed_client

    await client_a.post(
        "/api/packages",
        json={
            "tracking_number": "TRK-PRIVATE-A",
            "carrier": "DHL",
            "estimated_delivery": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat(),
        },
        headers=headers_a,
    )

    response = await client_b.get("/api/packages/TRK-PRIVATE-A", headers=headers_b)
    assert response.status_code == 404  # existence itself isn't leaked to a non-owner


@pytest.mark.asyncio
async def test_user_cannot_delete_another_users_package(authed_client, second_authed_client):
    client_a, headers_a = authed_client
    client_b, headers_b = second_authed_client

    await client_a.post(
        "/api/packages",
        json={
            "tracking_number": "TRK-PRIVATE-B",
            "carrier": "DHL",
            "estimated_delivery": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat(),
        },
        headers=headers_a,
    )

    delete_response = await client_b.delete("/api/packages/TRK-PRIVATE-B", headers=headers_b)
    assert delete_response.status_code == 404

    still_there = await client_a.get("/api/packages/TRK-PRIVATE-B", headers=headers_a)
    assert still_there.status_code == 200


@pytest.mark.asyncio
async def test_user_cannot_route_optimize_over_another_users_package(authed_client, second_authed_client):
    client_a, headers_a = authed_client
    client_b, headers_b = second_authed_client

    await client_a.post(
        "/api/packages",
        json={
            "tracking_number": "TRK-PRIVATE-C",
            "carrier": "DHL",
            "status": "Ready for Pickup",
            "pickup_location": "Ullmann Building",
            "estimated_delivery": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat(),
            "arrival_date": datetime.now(timezone.utc).isoformat(),
        },
        headers=headers_a,
    )

    response = await client_b.post(
        "/api/routing/optimize", json={"tracking_numbers": ["TRK-PRIVATE-C"]}, headers=headers_b
    )
    # User B owns none of the requested tracking numbers -> no locations found.
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "NO_PICKUP_LOCATIONS"
