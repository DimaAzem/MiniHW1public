"""
Test-only endpoints for injecting fake data during automated testing.

ONLY registered on the app when ENABLE_TEST_ENDPOINTS=true (see
backend/main.py) - when that flag is unset or false, this router is never
included at all, so these routes return a plain 404 in any real deployment,
not just a permission error. NEVER set this flag in a real deployment: it
has no auth of its own and can wipe every collection.
"""

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from backend.database.connection import get_database
from backend.seed_data import seed_database

router = APIRouter()


class InjectDelayEventRequest(BaseModel):
    user_id: str
    tracking_number: str
    carrier: str = "DHL"
    delay_probability: float = Field(..., ge=0.0, le=1.0)
    risk_level: str = "high"


@router.post(
    "/test/inject-delay-event",
    status_code=201,
    tags=["test-hooks"],
    summary="[TEST ONLY] Force a package into an arbitrary risk state",
)
async def inject_delay_event(
    payload: InjectDelayEventRequest, db: AsyncIOMotorDatabase = Depends(get_database)
) -> dict:
    document = {
        "_id": str(uuid4()),
        "user_id": payload.user_id,
        "tracking_number": payload.tracking_number,
        "carrier": payload.carrier,
        "status": "In Transit",
        "pickup_location": None,
        "estimated_delivery": datetime.now(timezone.utc),
        "arrival_date": None,
        "created_at": datetime.now(timezone.utc),
        "delay_probability": payload.delay_probability,
        "risk_level": payload.risk_level,
        "contributing_factors": ["Injected by /api/test/inject-delay-event for testing"],
    }
    await db.packages.update_one(
        {"user_id": payload.user_id, "tracking_number": payload.tracking_number},
        {"$set": document},
        upsert=True,
    )
    return {"status": "injected", "tracking_number": payload.tracking_number}


@router.post(
    "/test/seed-mock-data",
    tags=["test-hooks"],
    summary="[TEST ONLY] Run the seed script on demand",
)
async def trigger_seed(db: AsyncIOMotorDatabase = Depends(get_database)) -> dict:
    seeded = await seed_database(db)
    return {"seeded": seeded}


@router.delete(
    "/test/reset",
    tags=["test-hooks"],
    summary="[TEST ONLY] Wipe all collections",
)
async def reset_database(db: AsyncIOMotorDatabase = Depends(get_database)) -> dict:
    collection_names = await db.list_collection_names()
    for name in collection_names:
        await db[name].delete_many({})
    return {"status": "reset", "collections_cleared": collection_names}
