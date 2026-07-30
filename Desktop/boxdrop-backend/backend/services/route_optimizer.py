"""
Smart Pickup Route Optimizer.

Solves a small instance of the Traveling Salesperson Problem: given a set of
package pickup locations, find a short route that visits all of them,
starting from a fixed depot. TSP is NP-hard in general, so for a handful of
real-world stops a full optimal solver is unnecessary overhead - a greedy
nearest-neighbor heuristic gets within a reasonable factor of optimal and is
instant, deterministic, and trivial to explain in a course presentation.

Coordinates are simulated, not real GPS: known campus/city locations get a
fixed, hand-placed (x, y) in kilometers; anything else gets a deterministic
coordinate derived from a hash of its name, so the optimizer works robustly
for whatever free-text location a user types, not just the preset list.
"""

import hashlib
import math
from dataclasses import dataclass, field
from typing import List, Tuple

DEPOT_NAME = "BoxDrop Pickup Hub"

# Simulated coordinates (km, arbitrary local origin) for well-known Technion
# campus buildings and nearby Haifa postal/pickup locations. The depot sits
# at the origin; everything else is a hand-placed rough approximation of
# relative position, purely for a believable, demoable routing visualization.
KNOWN_NODES: dict[str, Tuple[float, float]] = {
    "boxdrop pickup hub": (0.0, 0.0),
    "ullmann building": (0.6, 0.4),
    "taub building": (0.9, 0.7),
    "churchill auditorium": (1.1, 0.3),
    "the technion student union": (0.3, 1.0),
    "segev building": (1.4, 1.1),
    "bloomfield building": (0.8, -0.3),
    "sego building": (1.7, 0.6),
    "nasher post office": (3.2, -1.8),
    "haifa central post office": (4.5, -3.1),
    "carmel center post office": (2.9, -4.4),
    "hadar post office": (3.8, -0.9),
    "grand kanyon locker": (5.1, -1.4),
    "horev center": (2.4, -3.6),
}

# Constant-speed assumption used only to translate distance saved into a
# human-friendly "time saved" figure - a local courier / scooter pace, not a
# claim about real traffic conditions.
ASSUMED_SPEED_KMH = 20.0


@dataclass
class RouteStop:
    name: str
    x: float
    y: float
    leg_distance_km: float  # distance from the previous stop (0 for the depot)


@dataclass
class RouteResult:
    stops: List[RouteStop] = field(default_factory=list)
    total_distance_km: float = 0.0
    naive_distance_km: float = 0.0
    estimated_time_minutes: float = 0.0
    estimated_time_saved_minutes: float = 0.0


def _coordinates_for(location_name: str) -> Tuple[float, float]:
    """Known campus/city node, or a deterministic hash-derived fallback."""
    key = location_name.strip().lower()
    if key in KNOWN_NODES:
        return KNOWN_NODES[key]

    digest = hashlib.md5(key.encode("utf-8")).hexdigest()
    # Two independent slices of the digest -> two roughly-uniform, stable
    # pseudo-random coordinates in a plausible city-scale range (km).
    x = (int(digest[0:8], 16) % 2000) / 100 - 10.0  # -10.0 .. +10.0
    y = (int(digest[8:16], 16) % 2000) / 100 - 10.0
    return (x, y)


def _distance(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.dist(a, b)


def _path_distance(coords: List[Tuple[float, float]]) -> float:
    return sum(_distance(coords[i], coords[i + 1]) for i in range(len(coords) - 1))


def optimize_route(location_names: List[str]) -> RouteResult:
    """
    Greedy nearest-neighbor TSP heuristic starting at the fixed depot.

    Args:
        location_names: Pickup-location strings for packages ready for
            pickup (duplicates are treated as separate stops - deduplicate
            before calling if that's not desired).

    Returns:
        A RouteResult with the visit order, per-leg and total distance, and
        a naive baseline (visiting locations in the given input order) for
        an honest "distance/time saved" comparison.
    """
    if not location_names:
        return RouteResult()

    depot_coords = KNOWN_NODES[DEPOT_NAME.lower()]
    remaining = [(name, _coordinates_for(name)) for name in location_names]

    # Naive baseline: depot -> locations in the order they were given.
    naive_path = [depot_coords] + [coords for _, coords in remaining]
    naive_distance = _path_distance(naive_path)

    # Greedy nearest-neighbor: repeatedly jump to the closest unvisited stop.
    route_stops: List[RouteStop] = []
    current = depot_coords
    unvisited = list(remaining)
    while unvisited:
        nearest_index = min(range(len(unvisited)), key=lambda i: _distance(current, unvisited[i][1]))
        name, coords = unvisited.pop(nearest_index)
        leg_distance = _distance(current, coords)
        route_stops.append(RouteStop(name=name, x=coords[0], y=coords[1], leg_distance_km=round(leg_distance, 3)))
        current = coords

    total_distance = sum(stop.leg_distance_km for stop in route_stops)
    estimated_time = (total_distance / ASSUMED_SPEED_KMH) * 60
    naive_time = (naive_distance / ASSUMED_SPEED_KMH) * 60

    return RouteResult(
        stops=route_stops,
        total_distance_km=round(total_distance, 3),
        naive_distance_km=round(naive_distance, 3),
        estimated_time_minutes=round(estimated_time, 1),
        estimated_time_saved_minutes=round(max(0.0, naive_time - estimated_time), 1),
    )
