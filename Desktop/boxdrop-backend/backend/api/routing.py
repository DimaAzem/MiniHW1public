"""
Smart Pickup Route Optimizer endpoint.

The client sends tracking numbers, not raw location strings - the server
looks up `pickup_location` from the caller's own packages, scoped by
user_id and status="Ready for Pickup". This means a user can only ever
route over locations extracted from packages they actually own.
"""

from typing import List

from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from backend.api.dependencies import get_current_user
from backend.database.connection import get_database
from backend.services.route_optimizer import RouteResult, optimize_route

router = APIRouter()


class NoPickupLocationsError(Exception):
    def __init__(self) -> None:
        super().__init__(
            "None of the requested tracking numbers matched a 'Ready for Pickup' "
            "package of yours with a pickup location set."
        )


class RouteOptimizeRequest(BaseModel):
    tracking_numbers: List[str]


class RouteStopResponse(BaseModel):
    name: str
    x: float
    y: float
    leg_distance_km: float


class RouteOptimizeResponse(BaseModel):
    stops: List[RouteStopResponse]
    total_distance_km: float
    naive_distance_km: float
    estimated_time_minutes: float
    estimated_time_saved_minutes: float


def _to_response(result: RouteResult) -> RouteOptimizeResponse:
    return RouteOptimizeResponse(
        stops=[
            RouteStopResponse(name=stop.name, x=stop.x, y=stop.y, leg_distance_km=stop.leg_distance_km)
            for stop in result.stops
        ],
        total_distance_km=result.total_distance_km,
        naive_distance_km=result.naive_distance_km,
        estimated_time_minutes=result.estimated_time_minutes,
        estimated_time_saved_minutes=result.estimated_time_saved_minutes,
    )


@router.post(
    "/routing/optimize",
    response_model=RouteOptimizeResponse,
    tags=["routing"],
    summary="Compute an optimized pickup route (greedy TSP heuristic)",
)
async def optimize_pickup_route(
    payload: RouteOptimizeRequest,
    username: str = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> RouteOptimizeResponse:
    cursor = db.packages.find(
        {
            "user_id": username,
            "tracking_number": {"$in": payload.tracking_numbers},
            "status": "Ready for Pickup",
        }
    )
    documents = await cursor.to_list(length=200)

    locations = [doc["pickup_location"] for doc in documents if doc.get("pickup_location")]
    if not locations:
        raise NoPickupLocationsError()

    result = optimize_route(locations)
    return _to_response(result)
