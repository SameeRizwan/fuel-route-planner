"""
Choose cost-effective fuel stops along a route.

Assumptions (stated in the assignment / README):
- Tank range is VEHICLE_MAX_RANGE_MILES (500).
- Vehicle gets VEHICLE_MPG (10) miles per gallon.
- Trip starts with a full tank (that fuel is not charged again).
- Any amount can be bought at a station, up to a full tank.
"""

from __future__ import annotations

import heapq

from django.conf import settings

from .exceptions import TripPlanningError


def plan_fuel_stops(
    route_stations: list[dict],
    distance_miles: float,
) -> dict:
    """
    Greedy cheapest-fuel plan using a min-heap of reachable stations.

    Returns gallons purchased, total USD, and the stop list.
    """
    max_range = float(settings.VEHICLE_MAX_RANGE_MILES)
    mpg = float(settings.VEHICLE_MPG)
    tank_gallons = max_range / mpg

    if distance_miles <= 0:
        return {
            "gallons_needed": 0.0,
            "gallons_purchased": 0.0,
            "total_cost_usd": 0.0,
            "fuel_stops": [],
        }

    # Destination is a final checkpoint where we never buy fuel.
    stops = [
        {
            "name": station["name"],
            "mile": float(station["mile"]),
            "price": float(station["price"]),
            "lat": station["lat"],
            "lon": station["lon"],
            "city": station["city"],
            "state": station["state"],
            "address": station["address"],
        }
        for station in route_stations
        if 0 < float(station["mile"]) < distance_miles
    ]
    stops.append(
        {
            "name": "DESTINATION",
            "mile": float(distance_miles),
            "price": None,
            "lat": None,
            "lon": None,
            "city": None,
            "state": None,
            "address": None,
            "is_destination": True,
        }
    )

    fuel_miles = max_range  # start full
    prev_mile = 0.0
    # heap entries: (price, sequence, gallons_room_left_at_station, station_dict)
    heap: list[tuple[float, int, float, dict]] = []
    seq = 0
    purchases: dict[int, dict] = {}

    for stop in stops:
        gap = stop["mile"] - prev_mile
        if gap > max_range and not heap and fuel_miles < gap:
            raise TripPlanningError(
                f"Cannot cover {gap:.1f} miles without a fuel stop "
                f"(max range is {max_range:.0f} miles)."
            )

        # Buy just enough from the cheapest stations already passed.
        while fuel_miles < gap:
            if not heap:
                raise TripPlanningError(
                    "No reachable fuel station within vehicle range "
                    f"near mile {prev_mile + fuel_miles:.1f}."
                )

            price, _, room, station = heapq.heappop(heap)
            if room <= 1e-9:
                continue

            need = gap - fuel_miles
            buy_miles = min(need, room)
            buy_gallons = buy_miles / mpg
            cost = buy_gallons * price

            station_id = id(station)
            if station_id not in purchases:
                purchases[station_id] = {
                    "name": station["name"],
                    "address": station["address"],
                    "city": station["city"],
                    "state": station["state"],
                    "lat": station["lat"],
                    "lon": station["lon"],
                    "mile": station["mile"],
                    "price_per_gallon": round(price, 4),
                    "gallons": 0.0,
                    "cost_usd": 0.0,
                }
            purchases[station_id]["gallons"] += buy_gallons
            purchases[station_id]["cost_usd"] += cost

            fuel_miles += buy_miles
            leftover = room - buy_miles
            if leftover > 1e-9:
                heapq.heappush(heap, (price, seq, leftover, station))
                seq += 1

        fuel_miles -= gap
        prev_mile = stop["mile"]

        if stop.get("is_destination"):
            break

        # Arriving at a station: we could fill up to a full tank here later.
        room = tank_gallons * mpg - fuel_miles
        if room > 1e-9:
            heapq.heappush(heap, (stop["price"], seq, room, stop))
            seq += 1

    fuel_stops = sorted(purchases.values(), key=lambda s: s["mile"])
    for stop in fuel_stops:
        stop["gallons"] = round(stop["gallons"], 2)
        stop["cost_usd"] = round(stop["cost_usd"], 2)

    gallons_purchased = round(sum(s["gallons"] for s in fuel_stops), 2)
    total_cost = round(sum(s["cost_usd"] for s in fuel_stops), 2)
    gallons_needed = round(distance_miles / mpg, 2)

    return {
        "gallons_needed": gallons_needed,
        "gallons_purchased": gallons_purchased,
        "total_cost_usd": total_cost,
        "fuel_stops": fuel_stops,
    }
