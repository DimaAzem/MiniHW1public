"""
Packages Router: user-scoped CRUD for tracked packages.

Every route requires auth (get_current_user) and every query/update/delete
filters by `user_id` - a user can never see, modify, or delete another
user's packages. This is what backend/tests/test_security_auth_required.py
verifies directly.
"""

from datetime import datetime, timedelta, timezone
from typing import List, Literal, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from backend.api.dependencies import get_current_user
from backend.database.connection import get_database
from backend.services.predictive_engine import predict_delay

router = APIRouter()

# How many days a "Ready for Pickup" package can sit before Return-to-Sender risk begins.
PICKUP_WINDOW_DAYS = 5

PackageStatus = Literal["In Transit", "Ready for Pickup", "Delivered"]


class PackageNotFoundError(Exception):
    def __init__(self, tracking_number: str) -> None:
        self.tracking_number = tracking_number
        super().__init__(f"Package with tracking number '{tracking_number}' was not found")


class DuplicateTrackingNumberError(Exception):
    def __init__(self, tracking_number: str) -> None:
        self.tracking_number = tracking_number
        super().__init__(f"You already have a package with tracking number '{tracking_number}'")


class PackageCreate(BaseModel):
    tracking_number: str = Field(..., examples=["TRK-99281-A"])
    carrier: str = Field(..., examples=["DHL"])
    status: PackageStatus = "In Transit"
    pickup_location: Optional[str] = Field(None, examples=["Ullmann Building"])
    estimated_delivery: datetime = Field(..., examples=["2026-07-20T15:00:00"])
    arrival_date: Optional[datetime] = Field(
        None, description="Set when the package actually arrives at the pickup location; starts the RTS expiry clock."
    )


class PackageUpdate(BaseModel):
    status: Optional[PackageStatus] = None
    pickup_location: Optional[str] = None
    arrival_date: Optional[datetime] = None


class PackageResponse(BaseModel):
    id: str
    user_id: str
    tracking_number: str
    carrier: str
    status: str
    pickup_location: Optional[str] = None
    estimated_delivery: datetime
    arrival_date: Optional[datetime] = None
    expiry_hours_left: Optional[float] = Field(
        None, description="Hours until Return-to-Sender risk, only set while status is 'Ready for Pickup'."
    )
    created_at: datetime
    delay_probability: float
    risk_level: str
    contributing_factors: List[str]


def _expiry_hours_left(pkg_status: str, arrival_date: Optional[datetime]) -> Optional[float]:
    """
    Computed at read-time (never stored) so it's never stale: the countdown
    reflects "now" on every single request, not whenever the package was last written.
    """
    if pkg_status != "Ready for Pickup" or arrival_date is None:
        return None
    # MongoDB's BSON datetime type carries no timezone - Motor reads back a
    # naive datetime even though we stored a UTC-aware one. It's always UTC
    # on the wire, so a naive value here just needs that tzinfo restored.
    if arrival_date.tzinfo is None:
        arrival_date = arrival_date.replace(tzinfo=timezone.utc)
    deadline = arrival_date + timedelta(days=PICKUP_WINDOW_DAYS)
    remaining_hours = (deadline - datetime.now(timezone.utc)).total_seconds() / 3600
    return round(max(0.0, remaining_hours), 1)


def _to_response(document: dict) -> PackageResponse:
    return PackageResponse(
        id=document["_id"],
        user_id=document["user_id"],
        tracking_number=document["tracking_number"],
        carrier=document["carrier"],
        status=document["status"],
        pickup_location=document.get("pickup_location"),
        estimated_delivery=document["estimated_delivery"],
        arrival_date=document.get("arrival_date"),
        expiry_hours_left=_expiry_hours_left(document["status"], document.get("arrival_date")),
        created_at=document["created_at"],
        delay_probability=document["delay_probability"],
        risk_level=document["risk_level"],
        contributing_factors=document["contributing_factors"],
    )


@router.post(
    "/packages",
    response_model=PackageResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["packages"],
    summary="Register a new package",
)
async def create_package(
    payload: PackageCreate,
    username: str = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> PackageResponse:
    prediction = predict_delay(payload.carrier, payload.estimated_delivery)

    document = {
        "_id": str(uuid4()),
        "user_id": username,
        "tracking_number": payload.tracking_number,
        "carrier": payload.carrier,
        "status": payload.status,
        "pickup_location": payload.pickup_location,
        "estimated_delivery": payload.estimated_delivery,
        "arrival_date": payload.arrival_date,
        "created_at": datetime.now(timezone.utc),
        "delay_probability": prediction.delay_probability,
        "risk_level": prediction.risk_level,
        "contributing_factors": prediction.contributing_factors,
    }
    try:
        await db.packages.insert_one(document)
    except DuplicateKeyError as exc:
        raise DuplicateTrackingNumberError(payload.tracking_number) from exc

    return _to_response(document)


@router.get(
    "/packages",
    response_model=List[PackageResponse],
    tags=["packages"],
    summary="List my packages",
)
async def list_packages(
    username: str = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database),
    limit: int = Query(200, ge=1, le=500),
    skip: int = Query(0, ge=0),
) -> List[PackageResponse]:
    cursor = db.packages.find({"user_id": username}).sort("created_at", -1).skip(skip).limit(limit)
    documents = await cursor.to_list(length=limit)
    return [_to_response(doc) for doc in documents]


@router.get(
    "/packages/{tracking_number}",
    response_model=PackageResponse,
    tags=["packages"],
    summary="Get one of my packages",
)
async def get_package(
    tracking_number: str,
    username: str = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> PackageResponse:
    document = await db.packages.find_one({"user_id": username, "tracking_number": tracking_number})
    if document is None:
        raise PackageNotFoundError(tracking_number)
    return _to_response(document)


@router.patch(
    "/packages/{tracking_number}",
    response_model=PackageResponse,
    tags=["packages"],
    summary="Update status or pickup details for one of my packages",
)
async def update_package(
    tracking_number: str,
    payload: PackageUpdate,
    username: str = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> PackageResponse:
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        document = await db.packages.find_one({"user_id": username, "tracking_number": tracking_number})
        if document is None:
            raise PackageNotFoundError(tracking_number)
        return _to_response(document)

    document = await db.packages.find_one_and_update(
        {"user_id": username, "tracking_number": tracking_number},
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )
    if document is None:
        raise PackageNotFoundError(tracking_number)
    return _to_response(document)


@router.delete(
    "/packages/{tracking_number}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["packages"],
    summary="Delete one of my packages",
)
async def delete_package(
    tracking_number: str,
    username: str = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> None:
    result = await db.packages.delete_one({"user_id": username, "tracking_number": tracking_number})
    if result.deleted_count == 0:
        raise PackageNotFoundError(tracking_number)
