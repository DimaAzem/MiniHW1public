"""Predictive Carrier Analytics endpoint."""

from datetime import date as date_cls
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.api.dependencies import get_current_user
from backend.services.carrier_analytics import predict_carrier_delay

router = APIRouter()


class CarrierPredictionRequest(BaseModel):
    carrier: str = Field(..., examples=["Israel Post"])
    target_date: Optional[date_cls] = Field(None, description="Defaults to today if omitted.")


class CarrierPredictionResponse(BaseModel):
    carrier: str
    target_date: date_cls
    delay_probability: float
    risk_level: str
    dynamic_eta_days: int
    narrative: str
    contributing_factors: List[str]


@router.post(
    "/analytics/predict",
    response_model=CarrierPredictionResponse,
    tags=["analytics"],
    summary="Forecast carrier delay risk and a dynamic ETA",
)
async def predict_carrier(
    payload: CarrierPredictionRequest, username: str = Depends(get_current_user)
) -> CarrierPredictionResponse:
    forecast = predict_carrier_delay(payload.carrier, payload.target_date)
    return CarrierPredictionResponse(**forecast.to_dict())
