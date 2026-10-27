"""
Geocoding, routing, and fuel planning for a US road trip.

Uses Nominatim (places → coordinates) and OSRM (coordinates → driving route).
Fuel stations come from the local CSV; map APIs are not used for prices.
"""

import hashlib
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.core.cache import cache

from .exceptions import TripPlanningError
from .fuel import plan_fuel_stops
from .geo import stations_along_route
from .stations import load_stations

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
    Build a full trip plan: route, nearby stations, and cheap fuel stops.

    Map/routing APIs are used only for geocoding and one driving route.
    """
    start = geocode(start_place)
    finish = geocode(finish_place)
    route = get_route(start, finish)

    nearby = stations_along_route(
        load_stations(),
        route["route_geojson"],
        max_detour_miles=settings.STATION_MAX_DETOUR_MILES,
    )
    fuel = plan_fuel_stops(nearby, route["distance_miles"])

    return {
        "start": start_place,
        "finish": finish_place,
        "start_location": start,
        "finish_location": finish,
        "distance_miles": route["distance_miles"],
        "duration_seconds": route["duration_seconds"],
        "mpg": settings.VEHICLE_MPG,
        "max_range_miles": settings.VEHICLE_MAX_RANGE_MILES,
        "gallons_needed": fuel["gallons_needed"],
        "gallons_purchased": fuel["gallons_purchased"],
        "total_cost_usd": fuel["total_cost_usd"],
        "fuel_stops": fuel["fuel_stops"],
        "stations_considered": len(nearby),
        "route_geojson": route["route_geojson"],
        "map_url": build_map_url(start, finish),
    }

