"""
Unit tests: the carrier delay forecasting model in isolation - pure function
calls against backend/services/carrier_analytics.py, no HTTP.
"""

from datetime import date

from backend.services.carrier_analytics import predict_carrier_delay


def test_probability_always_stays_in_valid_range():
    for carrier in ["DHL", "FedEx", "Israel Post", "Some Unknown Carrier"]:
        forecast = predict_carrier_delay(carrier, date(2026, 7, 15))
        assert 0.0 <= forecast.delay_probability <= 1.0


def test_worst_case_combination_reaches_genuinely_high_risk():
    # Israel Post (highest base delay rate) + Sunday (heaviest congestion
    # multiplier) + the Jewish High Holidays window, all compounding
    # multiplicatively - this is exactly the scenario this model exists to
    # capture, unlike the conservative per-package engine which tops out
    # around ~20% even in its worst case.
    forecast = predict_carrier_delay("Israel Post", date(2026, 9, 20))  # a Sunday within the holiday window
    assert forecast.delay_probability >= 0.6
    assert forecast.risk_level == "high"
    assert "israel post" in forecast.narrative.lower()


def test_best_case_combination_is_low_risk():
    forecast = predict_carrier_delay("FedEx", date(2026, 7, 15))  # a calm Wednesday, no holiday window
    assert forecast.risk_level == "low"


def test_narrative_mentions_the_carrier_name_and_a_percentage():
    forecast = predict_carrier_delay("DHL", date(2026, 7, 15))
    assert "DHL" in forecast.narrative
    assert "%" in forecast.narrative


def test_dynamic_eta_is_at_least_the_carriers_base_transit_time():
    # Israel Post's base transit time is 7 days; the dynamic ETA only ever adds on top.
    forecast = predict_carrier_delay("Israel Post", date(2026, 7, 15))
    assert forecast.dynamic_eta_days >= 7


def test_unknown_carrier_falls_back_to_a_sane_default_rather_than_crashing():
    forecast = predict_carrier_delay("Some Carrier Nobody Has Heard Of", date(2026, 7, 15))
    assert 0.0 <= forecast.delay_probability <= 1.0
    assert forecast.dynamic_eta_days > 0
