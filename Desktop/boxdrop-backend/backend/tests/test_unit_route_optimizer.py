"""
Unit tests: the greedy nearest-neighbor TSP heuristic in isolation - pure
function calls against backend/services/route_optimizer.py, no HTTP.
"""

from backend.services.route_optimizer import _coordinates_for, optimize_route


def test_optimize_route_visits_every_requested_location_exactly_once():
    locations = ["Ullmann Building", "Nasher Post Office", "Taub Building"]
    result = optimize_route(locations)
    assert sorted(stop.name for stop in result.stops) == sorted(locations)
    assert len(result.stops) == len(locations)


def test_optimize_route_total_distance_matches_sum_of_legs():
    result = optimize_route(["Ullmann Building", "Segev Building", "Bloomfield Building"])
    assert result.total_distance_km == round(sum(stop.leg_distance_km for stop in result.stops), 3)


def test_optimize_route_picks_the_nearest_stop_first():
    # From the depot (0,0), Ullmann Building (0.6, 0.4) is much closer than
    # Haifa Central Post Office (4.5, -3.1) - nearest-neighbor must visit it first.
    result = optimize_route(["Haifa Central Post Office", "Ullmann Building"])
    assert result.stops[0].name == "Ullmann Building"


def test_optimize_route_handles_a_single_location():
    result = optimize_route(["Nasher Post Office"])
    assert len(result.stops) == 1
    assert result.stops[0].leg_distance_km > 0  # distance from the depot


def test_optimize_route_handles_empty_input():
    result = optimize_route([])
    assert result.stops == []
    assert result.total_distance_km == 0.0
    assert result.estimated_time_saved_minutes == 0.0


def test_optimized_route_is_never_longer_than_the_naive_baseline():
    # A greedy heuristic can tie a naive ordering but should never do worse -
    # this holds for nearest-neighbor specifically when compared against an
    # arbitrary (non-optimized) visiting order of the same stops.
    locations = ["Haifa Central Post Office", "Ullmann Building", "Carmel Center Post Office", "Segev Building"]
    result = optimize_route(locations)
    assert result.total_distance_km <= result.naive_distance_km


def test_unknown_location_gets_a_deterministic_stable_coordinate():
    coords_a = _coordinates_for("Some Random Locker #42")
    coords_b = _coordinates_for("Some Random Locker #42")
    assert coords_a == coords_b  # same input -> same output, every call

    coords_different = _coordinates_for("A Totally Different Locker")
    assert coords_a != coords_different
