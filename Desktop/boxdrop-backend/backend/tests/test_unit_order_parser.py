"""
Unit tests: the order/shipping-text parser and its anti-hallucination
validation guardrail, in isolation - no HTTP, no database.
"""

from datetime import datetime, timedelta, timezone

from backend.services.order_parser import parse_order_text


def test_parses_a_complete_order_confirmation():
    text = (
        "Your DHL package is on its way!\n"
        "Tracking Number: TRK-99281-A\n"
        "Item: Wireless Headphones\n"
        f"Estimated delivery: {(datetime.now(timezone.utc) + timedelta(days=5)).strftime('%B %d, %Y')}.\n"
    )
    result = parse_order_text(text)
    assert result.carrier == "DHL"
    assert result.tracking_number == "TRK-99281-A"
    assert result.estimated_delivery is not None
    assert result.validation_errors == []
    assert result.confidence_score > 0.5


def test_guardrail_rejects_an_implausibly_long_tracking_number():
    long_value = "a" * 40
    text = f"Your order shipped. Tracking Number: {long_value}."
    result = parse_order_text(text)
    assert result.tracking_number is None
    assert any("tracking number" in err.lower() for err in result.validation_errors)


def test_guardrail_rejects_a_delivery_date_far_in_the_past():
    text = "Your DHL package shipped. Estimated delivery: January 1, 2020."
    result = parse_order_text(text)
    assert result.estimated_delivery is None
    assert any("estimated_delivery" in err for err in result.validation_errors)


def test_guardrail_accepts_a_near_term_past_date_within_grace_period():
    # A date 1 day in the past is within the grace window (email processed a day late) - not rejected.
    near_past = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%B %d, %Y")
    text = f"Your FedEx package shipped. Estimated delivery: {near_past}."
    result = parse_order_text(text)
    assert result.estimated_delivery is not None
    assert result.validation_errors == []


def test_preferred_carrier_used_only_when_text_has_no_explicit_carrier():
    text = "Tracking Number: TRK-11111-B. Your package is on its way."
    result = parse_order_text(text, preferred_carrier="Israel Post")
    assert result.carrier == "Israel Post"


def test_preferred_carrier_never_overrides_an_explicit_match_in_the_text():
    text = "Your DHL package shipped. Tracking Number: TRK-22222-C."
    result = parse_order_text(text, preferred_carrier="Israel Post")
    assert result.carrier == "DHL"


def test_detects_subscription_status_keywords():
    text = "Your subscribe & save order has shipped via UPS."
    result = parse_order_text(text)
    assert result.subscription_status == "Active Subscription"


def test_vague_email_extracts_nothing_and_has_zero_confidence():
    result = parse_order_text("Thanks for shopping with us!")
    assert result.carrier is None
    assert result.tracking_number is None
    assert result.confidence_score == 0.0
