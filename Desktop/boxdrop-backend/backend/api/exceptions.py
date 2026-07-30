"""
Exceptions Router: user-scoped access to flagged high-risk packages.

Exception records are written by the background worker (backend/worker.py)
whenever a package's re-scored risk newly crosses into "high" - not on
every worker cycle, only the first time, so a user's exception feed isn't
flooded with repeats for the same still-high-risk package.
"""

from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from backend.api.dependencies import get_current_user
from backend.database.connection import get_database

router = APIRouter()


class ExceptionResponse(BaseModel):
    tracking_number: str
    risk_score: float
    reason: str
    flagged_at: datetime


@router.get(
    "/exceptions",
    response_model=List[ExceptionResponse],
    tags=["exceptions"],
    summary="List my flagged high-risk packages",
)
async def list_exceptions(
    username: str = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database),
    limit: int = Query(100, ge=1, le=500),
) -> List[ExceptionResponse]:
    cursor = db.exceptions.find({"user_id": username}).sort("flagged_at", -1).limit(limit)
    documents = await cursor.to_list(length=limit)
    return [
        ExceptionResponse(
            tracking_number=doc["tracking_number"],
            risk_score=doc["risk_score"],
            reason=doc["reason"],
            flagged_at=doc["flagged_at"],
        )
        for doc in documents
    ]
