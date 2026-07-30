"""
End-to-end (system) test: one full user journey through the real ASGI app -
register, log in, track packages, optimize a pickup route, and check a
carrier forecast - asserting the whole chain is coherent, not just each
endpoint in isolation.
"""

from datetime import datetime, timedelta, timezone

import pytest


@pytest.mark.asyncio
async def test_full_user_journey(client):
    # 1. Register
    register_response = await client.post(
        "/api/auth/register", json={"username": "journey_user", "password": "JourneyPass123"}
    )
    assert register_response.status_code == 201

    # 2. Log in
    login_response = await client.post(
        "/api/auth/login", json={"username": "journey_user", "password": "JourneyPass123"}
    )
    assert login_response.status_code == 200
    token = login_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 3. Create two packages, both ready for pickup at real campus locations
    future_delivery = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    arrival = datetime.now(timezone.utc).isoformat()
    for tracking, carrier, location in [
        ("TRK-JOURNEY-1", "DHL", "Ullmann Building"),
        ("TRK-JOURNEY-2", "Israel Post", "Nasher Post Office"),
    ]:
        create_response = await client.post(
            "/api/packages",
            json={
                "tracking_number": tracking,
                "carrier": carrier,
                "status": "Ready for Pickup",
                "pickup_location": location,
                "estimated_delivery": future_delivery,
                "arrival_date": arrival,
            },
            headers=headers,
        )
        assert create_response.status_code == 201

    # 4. Dashboard should show both packages
    list_response = await client.get("/api/packages", headers=headers)
    assert list_response.status_code == 200
    trackings = {p["tracking_number"] for p in list_response.json()}
    assert trackings == {"TRK-JOURNEY-1", "TRK-JOURNEY-2"}

    # 5. Optimize a pickup route across both
    route_response = await client.post(
        "/api/routing/optimize",
        json={"tracking_numbers": ["TRK-JOURNEY-1", "TRK-JOURNEY-2"]},
        headers=headers,
    )
    assert route_response.status_code == 200
    route_body = route_response.json()
    assert len(route_body["stops"]) == 2
    assert route_body["total_distance_km"] > 0

    # 6. Check a carrier delay forecast before placing a future order
    forecast_response = await client.post("/api/analytics/predict", json={"carrier": "Israel Post"}, headers=headers)
    assert forecast_response.status_code == 200
    forecast_body = forecast_response.json()
    assert 0.0 <= forecast_body["delay_probability"] <= 1.0
    assert "Israel Post" in forecast_body["narrative"]
