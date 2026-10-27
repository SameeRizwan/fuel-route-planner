"""
Geocoding and routing for trip planning.

Uses Nominatim (places → coordinates) and OSRM (coordinates → driving route).
Results are cached so a repeated request does not hit those APIs again.
"""

import hashlib
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.core.cache import cache

from .exceptions import TripPlanningError

METERS_PER_MILE = 1609.344


def _cache_key(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.lower().strip().encode()).hexdigest()[:32]
    return f"trips:{prefix}:{digest}"


def geocode(place: str) -> dict:
    """Resolve a place name to a US latitude/longitude."""
    place = place.strip()
    key = _cache_key("geocode", place)
    cached = cache.get(key)
    if cached is not None:
        return cached

    response = requests.get(
        settings.NOMINATIM_URL,
        params={
            "q": place,
            "format": "json",
            "limit": 1,
            "addressdetails": 1,
            "countrycodes": "us",
        },
        headers={"User-Agent": settings.MAP_USER_AGENT},
        timeout=settings.MAP_HTTP_TIMEOUT,
    )
    response.raise_for_status()
    results = response.json()
    if not results:
        raise TripPlanningError(f"No US location found for '{place}'.")

    hit = results[0]
    country = (hit.get("address") or {}).get("country_code", "").lower()
    if country and country != "us":
        raise TripPlanningError(f"'{place}' is outside the USA.")

    location = {
        "lat": float(hit["lat"]),
        "lon": float(hit["lon"]),
        "display_name": hit.get("display_name", place),
    }
    cache.set(key, location, settings.ROUTE_CACHE_TTL)
    return location


def get_route(start: dict, finish: dict) -> dict:
    """Fetch a single driving route between two coordinate pairs."""
    key = _cache_key(
        "route",
        f"{start['lat']},{start['lon']}|{finish['lat']},{finish['lon']}",
    )
    cached = cache.get(key)
    if cached is not None:
        return cached

    path = f"{start['lon']},{start['lat']};{finish['lon']},{finish['lat']}"
    response = requests.get(
        f"{settings.OSRM_URL}/{path}",
        params={"overview": "full", "geometries": "geojson"},
        headers={"User-Agent": settings.MAP_USER_AGENT},
        timeout=settings.MAP_HTTP_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()

    if payload.get("code") != "Ok" or not payload.get("routes"):
        raise TripPlanningError("No driving route found between those places.")

    route = payload["routes"][0]
    result = {
        "distance_miles": round(route["distance"] / METERS_PER_MILE, 2),
        "duration_seconds": int(route["duration"]),
        "route_geojson": route["geometry"],
    }
    cache.set(key, result, settings.ROUTE_CACHE_TTL)
    return result


def build_map_url(start: dict, finish: dict) -> str:
    query = urlencode(
        {
            "engine": "fossgis_osrm_car",
            "route": f"{start['lat']},{start['lon']};{finish['lat']},{finish['lon']}",
        }
    )
    return f"https://www.openstreetmap.org/directions?{query}"


def plan_trip(start_place: str, finish_place: str) -> dict:
    """
    Geocode start and finish, then request one driving route.

    Returns a JSON-serializable trip summary. Fuel stops are added later.
    """
    start = geocode(start_place)
    finish = geocode(finish_place)
    route = get_route(start, finish)

    return {
        "start": start_place,
        "finish": finish_place,
        "start_location": start,
        "finish_location": finish,
        "distance_miles": route["distance_miles"],
        "duration_seconds": route["duration_seconds"],
        "route_geojson": route["route_geojson"],
        "map_url": build_map_url(start, finish),
    }
