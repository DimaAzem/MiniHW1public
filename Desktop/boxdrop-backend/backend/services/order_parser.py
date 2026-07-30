"""
Order/shipping-notification parser with a post-extraction validation guardrail.

This is a regex/heuristic extractor, not an LLM - there is no generative
model anywhere in this stack, so there is no risk of the traditional LLM
"hallucination" failure mode. What "anti-hallucination guardrail" means here,
concretely: every extracted field is checked against a business rule before
it's trusted (a tracking number must look like a tracking number, a delivery
date can't be absurdly far in the past or future), and rejected fields are
reported back explicitly via `validation_errors`, never silently dropped or
guessed at.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from dateutil import parser as date_parser

# ---------------------------------------------------------------------------
# Carrier / vendor / item detection
# ---------------------------------------------------------------------------
KNOWN_CARRIERS = ["DHL Express", "DHL", "FedEx", "UPS", "USPS", "Israel Post", "Amazon Logistics"]
KNOWN_VENDORS = ["Amazon", "eBay", "Shein", "AliExpress", "Etsy", "Walmart", "Best Buy"]

TRACKING_NUMBER_PATTERNS = [
    r"\bTRK-\d{4,}-[A-Z0-9]+\b",          # e.g. TRK-99281-A
    r"\b1Z[0-9A-Z]{16}\b",                # UPS
    r"\b\d{12,14}\b",                     # FedEx / generic long numeric
    r"\bRR\d{9}IL\b",                     # Israel Post international
    r"\b[A-Z]{2}\d{9}[A-Z]{2}\b",         # generic UPU S10 format
]
TRACKING_LABEL_PATTERN = re.compile(
    r"(?:tracking(?:\s*number)?|tracking\s*#|tracking\s*id)\s*[:#-]?\s*([A-Za-z0-9-]{6,})",
    re.IGNORECASE,
)

DATE_LABEL_PATTERN = re.compile(
    r"(?:estimated\s*delivery|arriving|arrives?|delivery\s*date|expected\s*(?:by|delivery))"
    r"\s*(?:on|by|:)?\s*([A-Za-z0-9,\s/-]{6,32}?)(?:\.|\n|$)",
    re.IGNORECASE,
)

ITEM_LABEL_PATTERN = re.compile(
    r"(?:item|product|order)\s*[:#-]?\s*([A-Za-z0-9 ,.'\-]{3,60}?)(?:\.|\n|$)",
    re.IGNORECASE,
)

SUBSCRIPTION_KEYWORDS = {
    "Cancelled Subscription": ["subscription cancelled", "subscription canceled", "auto-renew cancelled", "auto-renew canceled"],
    "Active Subscription": ["subscribe & save", "subscription renewed", "auto-delivery", "recurring delivery"],
}

# ---------------------------------------------------------------------------
# Anti-hallucination guardrail thresholds
# ---------------------------------------------------------------------------
MAX_PAST_DAYS = 2       # a delivery date more than this far in the past is almost certainly a mis-parse
MAX_FUTURE_DAYS = 365   # more than a year out is not a real shipping estimate
TRACKING_NUMBER_PATTERN = re.compile(r"^[A-Za-z0-9-]{4,30}$")


@dataclass
class ParsedOrderResult:
    carrier: Optional[str] = None
    vendor_name: Optional[str] = None
    tracking_number: Optional[str] = None
    estimated_delivery: Optional[datetime] = None
    item_name: Optional[str] = None
    subscription_status: Optional[str] = None
    confidence_score: float = 0.0
    validation_errors: List[str] = field(default_factory=list)


def _detect_from_list(text: str, candidates: List[str]) -> Optional[str]:
    for candidate in candidates:
        if re.search(re.escape(candidate), text, re.IGNORECASE):
            return candidate
    return None


def _detect_tracking_number(text: str) -> Optional[str]:
    for pattern in TRACKING_NUMBER_PATTERNS:
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    label_match = TRACKING_LABEL_PATTERN.search(text)
    if label_match:
        return label_match.group(1).strip().rstrip(".")
    return None


def _detect_estimated_delivery(text: str) -> Optional[datetime]:
    match = DATE_LABEL_PATTERN.search(text)
    if not match:
        return None
    candidate = match.group(1).strip()
    try:
        return date_parser.parse(candidate, fuzzy=True, dayfirst=False)
    except (ValueError, OverflowError):
        return None


def _detect_item_name(text: str) -> Optional[str]:
    match = ITEM_LABEL_PATTERN.search(text)
    if not match:
        return None
    return match.group(1).strip().rstrip(".")


def _detect_subscription_status(text: str) -> Optional[str]:
    lowered = text.lower()
    for status, keywords in SUBSCRIPTION_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return status
    return None


def _validate(result: ParsedOrderResult, now: Optional[datetime] = None) -> None:
    """
    The guardrail: checks each already-extracted field against a business
    rule and clears + reports any that fail, rather than trusting extraction
    output blindly. Mutates `result` in place.
    """
    now = now or datetime.now(timezone.utc)

    if result.tracking_number and not TRACKING_NUMBER_PATTERN.match(result.tracking_number):
        result.validation_errors.append(
            f"Rejected tracking number '{result.tracking_number}': doesn't match a plausible tracking-ID format."
        )
        result.tracking_number = None

    if result.estimated_delivery:
        delivery = result.estimated_delivery
        if delivery.tzinfo is None:
            delivery = delivery.replace(tzinfo=timezone.utc)
        if delivery < now - timedelta(days=MAX_PAST_DAYS):
            result.validation_errors.append(
                f"Rejected estimated_delivery '{delivery.date()}': more than {MAX_PAST_DAYS} days in the past."
            )
            result.estimated_delivery = None
        elif delivery > now + timedelta(days=MAX_FUTURE_DAYS):
            result.validation_errors.append(
                f"Rejected estimated_delivery '{delivery.date()}': more than {MAX_FUTURE_DAYS} days in the future."
            )
            result.estimated_delivery = None


def parse_order_text(raw_text: str, preferred_carrier: Optional[str] = None) -> ParsedOrderResult:
    """
    Extracts structured order/shipment fields from raw text, then runs the
    validation guardrail before returning.

    Args:
        raw_text: Raw email/order confirmation text.
        preferred_carrier: A user's historically-confirmed carrier (from
            preference_service), consulted ONLY as a tie-breaker when the
            text itself doesn't clearly name a carrier - never overrides an
            explicit match found in the text.
    """
    carrier = _detect_from_list(raw_text, KNOWN_CARRIERS)
    if carrier is None and preferred_carrier:
        carrier = preferred_carrier

    vendor_name = _detect_from_list(raw_text, KNOWN_VENDORS)
    tracking_number = _detect_tracking_number(raw_text)
    estimated_delivery = _detect_estimated_delivery(raw_text)
    item_name = _detect_item_name(raw_text)
    subscription_status = _detect_subscription_status(raw_text)

    result = ParsedOrderResult(
        carrier=carrier,
        vendor_name=vendor_name,
        tracking_number=tracking_number,
        estimated_delivery=estimated_delivery,
        item_name=item_name,
        subscription_status=subscription_status,
    )

    _validate(result)

    fields_found = sum(1 for value in (result.carrier, result.tracking_number, result.estimated_delivery) if value)
    result.confidence_score = round(min(fields_found / 3, 1.0), 4)

    return result
