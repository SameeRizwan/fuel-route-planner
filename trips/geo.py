"""Geometry helpers for placing stations along a driving route."""

from __future__ import annotations

import math
from collections import defaultdict

EARTH_RADIUS_MILES = 3958.7613


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS84 points, in miles."""
    rlat1, rlon1, rlat2, rlon2 = map(math.radians, (lat1, lon1, lat2, lon2))
    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


def build_route_samples(
    geojson_line: dict,
    sample_every_miles: float = 5.0,
) -> list[dict]:
    """
    Walk a GeoJSON LineString and emit points with cumulative mile markers.

    Coordinates in GeoJSON are [lon, lat].
    """
    coords = geojson_line.get("coordinates") or []
    if len(coords) < 2:
        return []

    samples: list[dict] = []
    prev_lon, prev_lat = coords[0]
    mile = 0.0
    samples.append({"lat": prev_lat, "lon": prev_lon, "mile": 0.0})
    next_sample_at = sample_every_miles

    for lon, lat in coords[1:]:
        segment = haversine_miles(prev_lat, prev_lon, lat, lon)
        if segment == 0:
            continue

        traveled = 0.0
        while mile + (segment - traveled) >= next_sample_at:
            step = next_sample_at - mile
            ratio = (traveled + step) / segment
            samples.append(
                {
                    "lat": prev_lat + (lat - prev_lat) * ratio,
                    "lon": prev_lon + (lon - prev_lon) * ratio,
                    "mile": round(next_sample_at, 3),
                }
            )
            traveled += step
            mile = next_sample_at
            next_sample_at += sample_every_miles

        mile += segment - traveled
        prev_lat, prev_lon = lat, lon

    end_lon, end_lat = coords[-1]
    last = samples[-1]
    if last["lat"] != end_lat or last["lon"] != end_lon:
        samples.append({"lat": end_lat, "lon": end_lon, "mile": round(mile, 3)})

    return samples


def _grid_key(lat: float, lon: float, cell: float) -> tuple[int, int]:
    return (int(math.floor(lat / cell)), int(math.floor(lon / cell)))


def stations_along_route(
    stations: tuple[dict, ...],
    route_geojson: dict,
    max_detour_miles: float,
) -> list[dict]:
    """
    Keep stations near the route and attach a mile marker to each.

    When several stations map to the same mile bucket, the cheapest is kept.
    """
    samples = build_route_samples(route_geojson)
    if not samples:
        return []

    lats = [p["lat"] for p in samples]
    lons = [p["lon"] for p in samples]
    pad = (max_detour_miles / 69.0) + 0.05
    min_lat, max_lat = min(lats) - pad, max(lats) + pad
    min_lon, max_lon = min(lons) - pad, max(lons) + pad

    # ~0.2° ≈ 14 miles — nearby cells cover the detour window.
    cell = 0.2
    grid: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for point in samples:
        grid[_grid_key(point["lat"], point["lon"], cell)].append(point)

    best_by_mile: dict[int, dict] = {}

    for station in stations:
        lat = station["lat"]
        lon = station["lon"]
        if not (min_lat <= lat <= max_lat and min_lon <= lon <= max_lon):
            continue

        gi, gj = _grid_key(lat, lon, cell)
        closest = None
        closest_dist = max_detour_miles

        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for point in grid.get((gi + di, gj + dj), ()):
                    dist = haversine_miles(lat, lon, point["lat"], point["lon"])
                    if dist <= closest_dist:
                        closest_dist = dist
                        closest = point

        if closest is None:
            continue

        mile_key = int(round(closest["mile"]))
        candidate = {
            **station,
            "mile": round(closest["mile"], 2),
            "detour_miles": round(closest_dist, 2),
        }
        existing = best_by_mile.get(mile_key)
        if existing is None or candidate["price"] < existing["price"]:
            best_by_mile[mile_key] = candidate

    return sorted(best_by_mile.values(), key=lambda s: s["mile"])
