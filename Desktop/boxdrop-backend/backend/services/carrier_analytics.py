"""
Predictive Carrier Analytics.

Powers the "Carrier Delay Predictor" page: given just a carrier name (and
optionally a target date), forecasts this week's delay risk and a dynamic
ETA - useful *before* placing an order, unlike predictive_engine.predict_delay
which scores a specific already-created package.

This is a deliberately separate, differently-calibrated model, not a reuse
of predictive_engine.py. That engine is intentionally conservative (weighted
additive factors that top out around ~20% even in the worst case) because it
scores real packages and shouldn't cry wolf. This model uses multiplicative
factors against a mock "historical dataset" specifically so a genuinely bad
combination (an unreliable carrier, a congested day, active holiday season)
can compound into a believable high-risk forecast, e.g. "85% chance of delay
this week for Israel Post due to holiday backlog."
"""

from dataclasses import dataclass, field
from datetime import date as date_cls
from datetime import datetime, timedelta
from typing import List, Optional

# ---------------------------------------------------------------------------
# Mock historical dataset: base delay rate per carrier
# ---------------------------------------------------------------------------
CARRIER_BASE_DELAY_RATE = {
    "dhl": 0.08,
    "fedex": 0.06,
    "ups": 0.07,
    "israel post": 0.38,
    "usps": 0.15,
    "amazon logistics": 0.10,
}
DEFAULT_BASE_DELAY_RATE = 0.20

# Average transit time (days) used for the dynamic ETA estimate.
CARRIER_BASE_TRANSIT_DAYS = {
    "dhl": 3,
    "fedex": 3,
    "ups": 4,
    "israel post": 7,
    "usps": 6,
    "amazon logistics": 4,
}
DEFAULT_BASE_TRANSIT_DAYS = 5

# ---------------------------------------------------------------------------
# Day-of-week congestion multiplier (date.weekday(): Monday=0 ... Sunday=6)
# ---------------------------------------------------------------------------
DAY_OF_WEEK_MULTIPLIER = {
    0: 1.25,  # Monday - weekend backlog
    1: 1.0,
    2: 0.95,  # Wednesday - calmest day
    3: 1.0,
    4: 1.2,   # Friday - pre-weekend rush
    5: 1.1,
    6: 1.4,   # Sunday - first Israeli business day, heaviest backlog
}

# ---------------------------------------------------------------------------
# Holiday / high-season windows -> multiplier + label
# ---------------------------------------------------------------------------
HOLIDAY_WINDOWS = [
    ((11, 20), (11, 30), "Black Friday / Cyber Monday surge", 1.5),
    ((12, 1), (12, 31), "December holiday season surge", 1.4),
    ((1, 1), (1, 5), "New Year backlog", 1.3),
    ((9, 1), (10, 15), "Jewish High Holidays surge", 1.45),
]

MIN_PROBABILITY = 0.02
MAX_PROBABILITY = 0.97


@dataclass
class CarrierForecast:
    carrier: str
    target_date: date_cls
    delay_probability: float
    risk_level: str
    dynamic_eta_days: int
    narrative: str
    contributing_factors: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "carrier": self.carrier,
            "target_date": self.target_date.isoformat(),
            "delay_probability": round(self.delay_probability, 4),
            "risk_level": self.risk_level,
            "dynamic_eta_days": self.dynamic_eta_days,
            "narrative": self.narrative,
            "contributing_factors": self.contributing_factors,
        }


def _risk_level(probability: float) -> str:
    if probability >= 0.6:
        return "high"
    if probability >= 0.3:
        return "medium"
    return "low"


def _holiday_multiplier(target_date: date_cls) -> tuple[float, Optional[str]]:
    for (start_month, start_day), (end_month, end_day), label, multiplier in HOLIDAY_WINDOWS:
        start = date_cls(target_date.year, start_month, start_day)
        end = date_cls(target_date.year, end_month, end_day)
        if start <= target_date <= end:
            return multiplier, label
    return 1.0, None


def predict_carrier_delay(carrier: str, target_date: Optional[date_cls] = None) -> CarrierForecast:
    """
    Forecasts this week's delay risk and a dynamic ETA for a carrier.

    Args:
        carrier: Carrier name, e.g. "DHL", "Israel Post".
        target_date: Date to forecast for; defaults to today.

    Returns:
        A CarrierForecast with probability, risk tier, a narrative
        explanation, and a dynamic ETA in days.
    """
    target_date = target_date or datetime.now().date()
    carrier_key = carrier.strip().lower()

    base_rate = CARRIER_BASE_DELAY_RATE.get(carrier_key, DEFAULT_BASE_DELAY_RATE)
    day_multiplier = DAY_OF_WEEK_MULTIPLIER.get(target_date.weekday(), 1.0)
    holiday_multiplier, holiday_label = _holiday_multiplier(target_date)

    probability = base_rate * day_multiplier * holiday_multiplier
    probability = max(MIN_PROBABILITY, min(MAX_PROBABILITY, probability))

    base_transit_days = CARRIER_BASE_TRANSIT_DAYS.get(carrier_key, DEFAULT_BASE_TRANSIT_DAYS)
    dynamic_eta_days = base_transit_days + round(probability * 3)

    factors = [f"'{carrier}' historical delay rate is {base_rate:.0%} of shipments"]
    day_name = target_date.strftime("%A")
    if day_multiplier != 1.0:
        factors.append(f"{day_name} carries a {'higher' if day_multiplier > 1 else 'lower'} than average congestion load ({day_multiplier:.2f}x)")
    else:
        factors.append(f"{day_name} has typical congestion")

    if holiday_label:
        factors.append(f"Currently within the {holiday_label} window ({holiday_multiplier:.2f}x)")
        reason = holiday_label.lower()
    elif day_multiplier > 1.1:
        reason = f"{day_name.lower()} congestion"
    else:
        reason = "typical carrier performance variance"

    narrative = f"{probability:.0%} chance of delay this week for {carrier} due to {reason}."

    return CarrierForecast(
        carrier=carrier,
        target_date=target_date,
        delay_probability=probability,
        risk_level=_risk_level(probability),
        dynamic_eta_days=dynamic_eta_days,
        narrative=narrative,
        contributing_factors=factors,
    )
