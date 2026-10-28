"""Three provider calls at most: geocode each endpoint, then route once."""

import hashlib
import math
from time import perf_counter

import requests
from django.conf import settings
from django.core.cache import cache

from .exceptions import MapServiceError, TripPlanningError
from .fuel import plan_fuel_stops
from .geo import decode_polyline6, stations_along_route
from .stations import load_stations

METERS_PER_MILE = 1609.344


def _cache_key(prefix, value):
    """Keep cache keys short and ignore location spelling case/outer whitespace."""
    digest = hashlib.sha256(value.casefold().strip().encode()).hexdigest()[:32]
    return f"trips:v2:{prefix}:{digest}"


def _get_json(url, params):
    """Make one provider request, leaving HTTP failures for the API view to handle."""
    response = requests.get(
        url, params=params, headers={"User-Agent": settings.MAP_USER_AGENT},
        timeout=settings.MAP_HTTP_TIMEOUT,
    )
    response.raise_for_status()
    try:
        return response.json()
    except ValueError as exc:
        raise MapServiceError("Map service returned an invalid response.") from exc


def geocode(place):
    """Resolve a US place name, reusing a cached location when available."""
    key = _cache_key("geocode", place)
    cached = cache.get(key)
    if cached is not None:
        return cached
    results = _get_json(settings.NOMINATIM_URL, {
        "q": place.strip(), "format": "json", "limit": 1,
        "addressdetails": 1, "countrycodes": "us",
    })
    if not isinstance(results, list):
        raise MapServiceError("Geocoder returned an invalid response.")
    if not results:
        raise TripPlanningError(f"No US location found for '{place}'.")
    try:
        hit = results[0]
        country = hit["address"]["country_code"].lower()
        lat, lon = float(hit["lat"]), float(hit["lon"])
        if not (math.isfinite(lat) and math.isfinite(lon)
                and -90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("Invalid coordinate")
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise MapServiceError("Geocoder returned an invalid location.") from exc
    if country != "us":
        raise TripPlanningError(f"'{place}' is outside the USA.")
    location = {"lat": lat, "lon": lon, "display_name": hit.get("display_name", place)}
    cache.set(key, location, settings.ROUTE_CACHE_TTL)
    return location


def get_route(start, finish):
    """Fetch a driving route; OSRM expects longitude before latitude."""
    key = _cache_key("route", f"{start['lat']},{start['lon']}|{finish['lat']},{finish['lon']}")
    cached = cache.get(key)
    if cached is not None:
        return cached
    path = f"{start['lon']},{start['lat']};{finish['lon']},{finish['lat']}"
    payload = _get_json(f"{settings.OSRM_URL}/{path}", {
        # Keep every route point, but transfer a compact encoding from OSRM.
        "overview": "full", "geometries": "polyline6",
    })
    if not isinstance(payload, dict):
        raise MapServiceError("Routing service returned an invalid response.")
    if payload.get("code") in {"NoRoute", "NoSegment"}:
        raise TripPlanningError("No driving route found between those places.")
    try:
        if payload["code"] != "Ok":
            raise ValueError("Unexpected routing response")
        route = payload["routes"][0]
        distance, duration = float(route["distance"]), float(route["duration"])
        geometry = route["geometry"]
        if isinstance(geometry, str):
            geometry = {"type": "LineString", "coordinates": decode_polyline6(geometry)}
        if (not math.isfinite(distance) or distance < 0
                or not math.isfinite(duration) or duration < 0
                or geometry["type"] != "LineString" or len(geometry["coordinates"]) < 2):
            raise ValueError("Invalid route")
        for lon, lat in geometry["coordinates"]:
            if not (math.isfinite(lon) and math.isfinite(lat)
                    and -180 <= lon <= 180 and -90 <= lat <= 90):
                raise ValueError("Invalid geometry coordinate")
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise MapServiceError("Routing service returned an invalid route.") from exc
    result = {
        "distance_miles": distance / METERS_PER_MILE,
        "duration_seconds": int(duration),
        "route_geojson": geometry,
    }
    cache.set(key, result, settings.ROUTE_CACHE_TTL)
    return result


def _timed_call(timings, name, function, *args, **kwargs):
    """Record milliseconds for Postman's Server-Timing response header."""
    started = perf_counter()
    try:
        return function(*args, **kwargs)
    finally:
        timings[name] = (perf_counter() - started) * 1000


def plan_trip(start_place, finish_place, *, timings=None):
    """Combine local station prices, a driving route and the fuel purchase plan."""
    if timings is None:
        timings = {}
    path = settings.FUEL_PRICES_PATH
    # A changed dataset or vehicle setting must invalidate the cached plan.
    fingerprint = (str(path), path.stat().st_mtime_ns) if path.exists() else "missing"
    plan_inputs = (
        start_place.strip().casefold(),
        finish_place.strip().casefold(),
        fingerprint,
        settings.VEHICLE_MAX_RANGE_MILES,
        settings.VEHICLE_MPG,
        settings.STATION_MAX_DETOUR_MILES,
    )
    key = _cache_key("plan-v3", repr(plan_inputs))
    cached = _timed_call(timings, "cache", cache.get, key)
    if cached is not None:
        return cached
    stations = _timed_call(timings, "stations", load_stations)
    start = _timed_call(timings, "geocode_start", geocode, start_place)
    finish = _timed_call(timings, "geocode_finish", geocode, finish_place)
    route = _timed_call(timings, "routing", get_route, start, finish)
    nearby = _timed_call(
        timings, "matching", stations_along_route,
        stations,
        route["route_geojson"],
        max_detour_miles=settings.STATION_MAX_DETOUR_MILES,
        route_distance_miles=route["distance_miles"],
    )
    fuel = _timed_call(timings, "fuel", plan_fuel_stops, nearby, route["distance_miles"])
    warnings = [
        "Station detours are straight-line estimates, not verified driving distances or road access.",
        "Fuel stops are cost-effective candidates; global optimality with detours is not guaranteed.",
        "The vehicle starts full. Total cost covers purchases during the trip and excludes starting fuel.",
    ]
    if any(stop["coordinate_source"] != "verified" for stop in fuel["fuel_stops"]):
        warnings.insert(0, "Some fuel markers are city coordinates, not verified station locations.")
    result = {
        "start": start_place, "finish": finish_place,
        "start_location": start, "finish_location": finish, **route, **fuel,
        "mpg": settings.VEHICLE_MPG, "max_range_miles": settings.VEHICLE_MAX_RANGE_MILES,
        "initial_fuel_gallons": settings.VEHICLE_MAX_RANGE_MILES / settings.VEHICLE_MPG,
        "fuel_cost_basis": "purchases_during_trip", "starting_fuel_cost_included": False,
        "stations_considered": len(nearby),
        "warnings": warnings, "distance_basis": "route_plus_estimated_station_detours",
        "attribution": "© OpenStreetMap contributors (ODbL); routing by OSRM; OPIS fuel price CSV.",
    }
    cache.set(key, result, settings.ROUTE_CACHE_TTL)
    return result
