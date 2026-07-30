"""
Predictive Analytics Engine.

Produces a dynamic "probability of delay" for a package instead of a static
hardcoded arrival window. The model is intentionally rule-based rather than a
trained ML model: it is transparent, deterministic, requires no training
data, and every contributing factor can be explained back to the user, which
matters for an operational alerting system.

The probability is assembled from three independent signals, each expressed
as a value in [0, 1] and combined with fixed weights:

1. Carrier reliability   - historical on-time performance per carrier.
2. Day-of-week congestion - some weekdays are structurally busier.
3. Seasonal / holiday surge - known high-volume windows increase delay risk.

The weighted sum is clipped to [0, 1] and mapped to a discrete risk tier,
which in turn drives a recommended lead time for a proactive customer alert.

Note: this engine is intentionally conservative (max achievable probability
is roughly 20% for known carriers) and is used only for per-package risk at
creation time. The separate, purpose-built `carrier_analytics` module powers
the "Carrier Delay Predictor" page and is calibrated to reach a wider range.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import List, Tuple

# ---------------------------------------------------------------------------
# Historical carrier performance model
# ---------------------------------------------------------------------------
# `on_time_rate` approximates the fraction of shipments each carrier has
# historically delivered within its quoted window. The carrier's baseline
# delay risk is simply `1 - on_time_rate`.
CARRIER_ON_TIME_RATE = {
    "dhl": 0.91,
    "fedex": 0.93,
    "ups": 0.92,
    "israel post": 0.78,
    "usps": 0.85,
    "amazon logistics": 0.90,
}
DEFAULT_CARRIER_ON_TIME_RATE = 0.80  # unknown carriers assumed less reliable

# ---------------------------------------------------------------------------
# Day-of-week congestion model
# ---------------------------------------------------------------------------
# Monday = 0 ... Sunday = 6 (Python's date.weekday() convention).
# Sunday is the first business day of the week in Israel, so both Sunday and
# Monday inherit a weekend backlog. Friday carries a pre-weekend rush as
# carriers race to deliver before Saturday closures.
DAY_OF_WEEK_CONGESTION = {
    0: 0.10,  # Monday - weekend backlog
    1: 0.02,  # Tuesday
    2: 0.00,  # Wednesday - lowest congestion
    3: 0.03,  # Thursday
    4: 0.12,  # Friday - pre-weekend rush
    5: 0.05,  # Saturday - reduced operations in many regions
    6: 0.15,  # Sunday - first business day, weekend backlog clears through here
}

# ---------------------------------------------------------------------------
# High-season / holiday surge windows
# ---------------------------------------------------------------------------
# Inclusive (month, day) ranges, evaluated against the estimated delivery
# date's year. Represents periods of known parcel-volume surges that degrade
# carrier performance regardless of carrier or weekday.
SURGE_WINDOWS: List[Tuple[Tuple[int, int], Tuple[int, int], str, float]] = [
    ((11, 20), (11, 30), "Black Friday / Cyber Monday surge", 0.25),
    ((12, 1), (12, 31), "December holiday season surge", 0.20),
    ((1, 1), (1, 5), "New Year backlog", 0.15),
    ((7, 1), (7, 15), "Mid-year sales surge", 0.10),
]


@dataclass
class DelayPrediction:
    """Structured result of a delay-probability estimation."""

    carrier: str
    estimated_delivery: datetime
    delay_probability: float
    risk_level: str
    recommended_alert_hours_before: int
    contributing_factors: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "carrier": self.carrier,
            "estimated_delivery": self.estimated_delivery.isoformat(),
            "delay_probability": round(self.delay_probability, 4),
            "risk_level": self.risk_level,
            "recommended_alert_hours_before": self.recommended_alert_hours_before,
            "contributing_factors": self.contributing_factors,
        }


def _carrier_risk(carrier: str) -> Tuple[float, str]:
    on_time_rate = CARRIER_ON_TIME_RATE.get(carrier.strip().lower(), DEFAULT_CARRIER_ON_TIME_RATE)
    risk = round(1 - on_time_rate, 4)
    explanation = f"Carrier '{carrier}' historical on-time rate is {on_time_rate:.0%}"
    return risk, explanation


def _day_of_week_risk(delivery_date: date) -> Tuple[float, str]:
    weekday = delivery_date.weekday()
    risk = DAY_OF_WEEK_CONGESTION.get(weekday, 0.0)
    day_name = delivery_date.strftime("%A")
    explanation = f"Delivery falls on {day_name}, a {'high' if risk >= 0.1 else 'normal'}-congestion day"
    return risk, explanation


def _seasonal_surge_risk(delivery_date: date) -> Tuple[float, str]:
    for (start_month, start_day), (end_month, end_day), label, surge in SURGE_WINDOWS:
        start = date(delivery_date.year, start_month, start_day)
        end = date(delivery_date.year, end_month, end_day)
        if start <= delivery_date <= end:
            return surge, f"Delivery date falls within {label}"
    return 0.0, "No active high-season surge for this date"


def _risk_level(probability: float) -> str:
    if probability >= 0.6:
        return "high"
    if probability >= 0.3:
        return "medium"
    return "low"


def _recommended_alert_hours(probability: float) -> int:
    """
    Rule-based lead time for a proactive "your package may be delayed" alert.
    Higher risk warrants earlier warning so the customer has time to react
    (e.g. arrange an alternate pickup).
    """
    if probability >= 0.6:
        return 48
    if probability >= 0.3:
        return 24
    return 12


def predict_delay(carrier: str, estimated_delivery: datetime) -> DelayPrediction:
    """
    Compute a dynamic delay-probability estimate for a shipment.

    Args:
        carrier: Carrier name, e.g. "DHL", "FedEx", "Israel Post".
        estimated_delivery: The carrier-quoted estimated delivery datetime.

    Returns:
        A DelayPrediction with probability, risk tier, recommended alert
        lead time, and a human-readable explanation of each contributing
        factor (useful for both the API response and audit/debugging).
    """
    delivery_date = estimated_delivery.date()

    carrier_risk, carrier_explanation = _carrier_risk(carrier)
    dow_risk, dow_explanation = _day_of_week_risk(delivery_date)
    surge_risk, surge_explanation = _seasonal_surge_risk(delivery_date)

    # Weighted combination: carrier reliability is the dominant signal,
    # congestion and seasonal surge act as additive risk modifiers.
    combined = (0.6 * carrier_risk) + (0.2 * dow_risk) + (0.2 * surge_risk)
    probability = max(0.0, min(1.0, combined))

    return DelayPrediction(
        carrier=carrier,
        estimated_delivery=estimated_delivery,
        delay_probability=probability,
        risk_level=_risk_level(probability),
        recommended_alert_hours_before=_recommended_alert_hours(probability),
        contributing_factors=[carrier_explanation, dow_explanation, surge_explanation],
    )


# ---------------------------------------------------------------------------
# Dynamic re-scoring for already-created packages (used by the background
# worker, backend/worker.py) - layers one new signal on top of the same
# carrier/day-of-week/season factors: how long a package has sat "In
# Transit" past its estimated delivery date. `predict_delay` above stays
# untouched and keeps scoring brand-new packages at creation time, when
# there's no status history yet to layer on.
# ---------------------------------------------------------------------------
STALENESS_RISK_PER_DAY_OVERDUE = 0.15
MAX_STALENESS_RISK = 0.9


def _status_staleness_risk(status: str, estimated_delivery: datetime, now: datetime) -> Tuple[float, str]:
    """
    A package still "In Transit" well past its estimated delivery date is
    the clearest real-world signal that something has actually gone wrong -
    a stronger signal than any pre-shipment factor, and one that grows the
    longer it persists. Every other status either has no bearing on delay
    risk (Delivered) or is tracked by its own separate signal entirely
    (Ready for Pickup's Return-to-Sender countdown, see backend/api/packages.py).
    """
    if status != "In Transit":
        return 0.0, "Not currently in transit - no staleness signal."

    if estimated_delivery.tzinfo is None:
        estimated_delivery = estimated_delivery.replace(tzinfo=timezone.utc)
    days_overdue = (now - estimated_delivery).total_seconds() / 86400
    if days_overdue <= 0:
        return 0.0, "Still within its estimated delivery window."

    risk = min(MAX_STALENESS_RISK, days_overdue * STALENESS_RISK_PER_DAY_OVERDUE)
    return risk, f"Still 'In Transit' {days_overdue:.1f} day(s) past its estimated delivery date"


def recompute_risk_with_status(package_document: dict) -> DelayPrediction:
    """
    Re-scores an already-persisted package, factoring in how long it has
    been stuck in its current status. Called by the background worker on a
    schedule (backend/worker.py) - never at creation time, since a
    brand-new package has no status history yet.
    """
    carrier = package_document["carrier"]
    estimated_delivery = package_document["estimated_delivery"]
    pkg_status = package_document.get("status", "In Transit")
    now = datetime.now(timezone.utc)

    if estimated_delivery.tzinfo is None:
        estimated_delivery = estimated_delivery.replace(tzinfo=timezone.utc)

    carrier_risk, carrier_explanation = _carrier_risk(carrier)
    dow_risk, dow_explanation = _day_of_week_risk(estimated_delivery.date())
    surge_risk, surge_explanation = _seasonal_surge_risk(estimated_delivery.date())
    staleness_risk, staleness_explanation = _status_staleness_risk(pkg_status, estimated_delivery, now)

    base = (0.6 * carrier_risk) + (0.2 * dow_risk) + (0.2 * surge_risk)
    probability = max(0.0, min(1.0, base + staleness_risk))

    factors = [carrier_explanation, dow_explanation, surge_explanation]
    if staleness_risk > 0:
        factors.append(staleness_explanation)

    return DelayPrediction(
        carrier=carrier,
        estimated_delivery=estimated_delivery,
        delay_probability=probability,
        risk_level=_risk_level(probability),
        recommended_alert_hours_before=_recommended_alert_hours(probability),
        contributing_factors=factors,
    )
