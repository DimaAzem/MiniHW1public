"""
Order/shipping-notification parsing endpoint.

Parses raw text into structured fields, runs them through the validation
guardrail, and returns the result WITHOUT saving anything - the caller
reviews/confirms it and then calls POST /api/packages to actually persist
it, and POST /api/parser/confirm to record the confirmation as a future
preference signal. Nothing gets written to Mongo from a parse alone.
"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from backend.api.dependencies import get_current_user
from backend.database.connection import get_database
from backend.services.order_parser import parse_order_text
from backend.services.preference_service import get_preferred_carrier, record_confirmed_order

router = APIRouter()


class ParseOrderRequest(BaseModel):
    raw_text: str = Field(..., min_length=1, description="Raw order/shipping confirmation text.")


class ParseOrderResponse(BaseModel):
    carrier: Optional[str] = None
    vendor_name: Optional[str] = None
    tracking_number: Optional[str] = None
    estimated_delivery: Optional[datetime] = None
    item_name: Optional[str] = None
    subscription_status: Optional[str] = None
    confidence_score: float
    validation_errors: List[str]


class ConfirmOrderRequest(BaseModel):
    carrier: str
    vendor_name: Optional[str] = None


@router.post(
    "/parser/parse-order",
    response_model=ParseOrderResponse,
    tags=["parser"],
    summary="Parse raw order/shipping text into structured fields",
)
async def parse_order(
    payload: ParseOrderRequest,
    username: str = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> ParseOrderResponse:
    preferred_carrier = await get_preferred_carrier(db, username)
    result = parse_order_text(payload.raw_text, preferred_carrier=preferred_carrier)
    return ParseOrderResponse(**result.__dict__)


@router.post(
    "/parser/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["parser"],
    summary="Record a confirmed parse for future preference learning",
)
async def confirm_order(
    payload: ConfirmOrderRequest,
    username: str = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> None:
    await record_confirmed_order(db, username, payload.carrier, payload.vendor_name)
