"""
Unit tests: the status-staleness risk signal added to predictive_engine.py,
and recompute_risk_with_status() which layers it on top of the existing
carrier/day-of-week/season factors.
"""

from datetime import datetime, timedelta, timezone

from backend.services.predictive_engine import recompute_risk_with_status


def _package(status: str, days_from_now: float, carrier: str = "DHL") -> dict:
    return {
        "carrier": carrier,
        "estimated_delivery": datetime.now(timezone.utc) + timedelta(days=days_from_now),
        "status": status,
    }


def test_in_transit_package_within_window_has_no_staleness_boost():
    prediction = recompute_risk_with_status(_package("In Transit", days_from_now=2))
    assert not any("past its estimated delivery" in factor for factor in prediction.contributing_factors)


def test_in_transit_package_far_overdue_becomes_high_risk():
    # 5 days overdue -> 5 * 0.15 = 0.75 staleness alone, well past the "high" threshold.
    prediction = recompute_risk_with_status(_package("In Transit", days_from_now=-5))
    assert prediction.risk_level == "high"
    assert any("past its estimated delivery" in factor for factor in prediction.contributing_factors)


def test_delivered_package_has_no_staleness_signal_even_if_overdue():
    prediction = recompute_risk_with_status(_package("Delivered", days_from_now=-30))
    assert not any("past its estimated delivery" in factor for factor in prediction.contributing_factors)


def test_ready_for_pickup_package_has_no_staleness_signal():
    # Ready for Pickup has its own separate Return-to-Sender countdown
    # (backend/api/packages.py); it shouldn't also accrue delay-risk staleness.
    prediction = recompute_risk_with_status(_package("Ready for Pickup", days_from_now=-10))
    assert not any("past its estimated delivery" in factor for factor in prediction.contributing_factors)


def test_probability_stays_within_valid_range_even_when_extremely_overdue():
    prediction = recompute_risk_with_status(_package("In Transit", days_from_now=-1000))
    assert 0.0 <= prediction.delay_probability <= 1.0
