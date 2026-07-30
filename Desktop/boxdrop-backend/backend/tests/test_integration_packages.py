"""
Integration tests: package CRUD through the real ASGI app and real Motor
queries against mongomock. Two independent users share the same database -
these tests confirm their packages never leak into each other's view.
"""

from datetime import datetime, timedelta, timezone

import pytest


def _future_iso(days: int = 5) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


@pytest.mark.asyncio
async def test_create_and_get_package(authed_client):
    client, headers = authed_client
    payload = {"tracking_number": "TRK-1", "carrier": "DHL", "estimated_delivery": _future_iso()}
    create_response = await client.post("/api/packages", json=payload, headers=headers)
    assert create_response.status_code == 201
    body = create_response.json()
    assert body["tracking_number"] == "TRK-1"
    assert body["status"] == "In Transit"
    assert 0.0 <= body["delay_probability"] <= 1.0

    get_response = await client.get("/api/packages/TRK-1", headers=headers)
    assert get_response.status_code == 200
    assert get_response.json()["tracking_number"] == "TRK-1"


@pytest.mark.asyncio
async def test_duplicate_tracking_number_for_the_same_user_is_rejected(authed_client):
    client, headers = authed_client
    payload = {"tracking_number": "TRK-DUP", "carrier": "DHL", "estimated_delivery": _future_iso()}
    first = await client.post("/api/packages", json=payload, headers=headers)
    assert first.status_code == 201
    second = await client.post("/api/packages", json=payload, headers=headers)
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_update_status_to_ready_for_pickup_sets_expiry_countdown(authed_client):
    client, headers = authed_client
    payload = {"tracking_number": "TRK-2", "carrier": "Israel Post", "estimated_delivery": _future_iso()}
    await client.post("/api/packages", json=payload, headers=headers)

    update = {
        "status": "Ready for Pickup",
        "pickup_location": "Ullmann Building",
        "arrival_date": datetime.now(timezone.utc).isoformat(),
    }
    response = await client.patch("/api/packages/TRK-2", json=update, headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "Ready for Pickup"
    assert body["expiry_hours_left"] is not None
    assert body["expiry_hours_left"] > 0


@pytest.mark.asyncio
async def test_delete_package(authed_client):
    client, headers = authed_client
    payload = {"tracking_number": "TRK-DELETE-ME", "carrier": "UPS", "estimated_delivery": _future_iso()}
    await client.post("/api/packages", json=payload, headers=headers)

    delete_response = await client.delete("/api/packages/TRK-DELETE-ME", headers=headers)
    assert delete_response.status_code == 204

    get_response = await client.get("/api/packages/TRK-DELETE-ME", headers=headers)
    assert get_response.status_code == 404


@pytest.mark.asyncio
async def test_two_users_packages_never_leak_into_each_others_list(authed_client, second_authed_client):
    client_a, headers_a = authed_client
    client_b, headers_b = second_authed_client

    await client_a.post(
        "/api/packages",
        json={"tracking_number": "TRK-USER-A", "carrier": "DHL", "estimated_delivery": _future_iso()},
        headers=headers_a,
    )
    await client_b.post(
        "/api/packages",
        json={"tracking_number": "TRK-USER-B", "carrier": "FedEx", "estimated_delivery": _future_iso()},
        headers=headers_b,
    )

    list_a = (await client_a.get("/api/packages", headers=headers_a)).json()
    list_b = (await client_b.get("/api/packages", headers=headers_b)).json()

    assert [p["tracking_number"] for p in list_a] == ["TRK-USER-A"]
    assert [p["tracking_number"] for p in list_b] == ["TRK-USER-B"]


@pytest.mark.asyncio
async def test_same_tracking_number_is_allowed_across_different_users(authed_client, second_authed_client):
    # Two different users can each independently receive a package that
    # happens to share the same carrier-assigned tracking number.
    client_a, headers_a = authed_client
    client_b, headers_b = second_authed_client

    payload = {"tracking_number": "TRK-SHARED", "carrier": "DHL", "estimated_delivery": _future_iso()}
    response_a = await client_a.post("/api/packages", json=payload, headers=headers_a)
    response_b = await client_b.post("/api/packages", json=payload, headers=headers_b)

    assert response_a.status_code == 201
    assert response_b.status_code == 201
