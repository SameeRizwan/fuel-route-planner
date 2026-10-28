"""Forward-only, capacity-constrained fuel planning on an ordered route.

Without detours this is the standard next-cheaper-station greedy algorithm.
With straight-line station detours it is a cost-conscious heuristic: all legs
include the detours, but the globally cheapest choice of detours is not promised.
"""

from decimal import Decimal, ROUND_HALF_UP
import math

from django.conf import settings

from .exceptions import TripPlanningError

EPSILON = 1e-7


def _can_reach_finish(stations, distance_miles, max_range):
    """Work backward to find stations with a feasible onward journey."""
    can_finish = [False] * len(stations)
    for index in range(len(stations) - 1, -1, -1):
        station = stations[index]
        # Leaving a station includes the detour back to the main route.
        to_finish = distance_miles - station["mile"] + station["detour_miles"]
        if to_finish <= max_range + EPSILON:
            can_finish[index] = True
            continue

        for next_index in range(index + 1, len(stations)):
            next_station = stations[next_index]
            leg = next_station["mile"] - station["mile"] + station["detour_miles"]
            if leg > max_range + EPSILON:
                break
            if can_finish[next_index] and leg + next_station["detour_miles"] <= max_range + EPSILON:
                can_finish[index] = True
                break
    return can_finish


def plan_fuel_stops(route_stations: list[dict], distance_miles: float) -> dict:
    """Choose forward stops and track fuel purchases, tank levels and detours."""
    max_range = float(settings.VEHICLE_MAX_RANGE_MILES)
    mpg = float(settings.VEHICLE_MPG)
    if not math.isfinite(distance_miles) or distance_miles < 0:
        raise TripPlanningError("Route distance must be a finite, non-negative number.")

    stations = sorted(
        (dict(station, mile=float(station["mile"]),
              detour_miles=float(station.get("detour_miles", 0)))
         for station in route_stations if 0 <= float(station["mile"]) < distance_miles),
        key=lambda station: (station["mile"], float(station["price"]), station.get("opis_id", "")),
    )
    # Detours can make a cheap station a dead end even when a nearby alternative
    # permits the trip. Backward reachability prevents choosing those dead ends.
    can_finish = _can_reach_finish(stations, distance_miles, max_range)
    current_mile = current_detour = traveled = 0.0
    # Fuel is tracked as miles of range; convert to gallons only for purchases/output.
    remaining_range = max_range
    current = None
    index = -1
    purchases = []
    total_gallons = 0.0
    total_cost = Decimal("0")

    while True:
        to_finish = distance_miles - current_mile + current_detour
        if to_finish <= remaining_range + EPSILON:
            traveled += to_finish
            break

        reachable = []
        for i in range(index + 1, len(stations)):
            station = stations[i]
            along = station["mile"] - current_mile
            if along + current_detour > max_range + EPSILON:
                break
            # Each leg includes returning to the route and reaching the next pump.
            leg = along + current_detour + station["detour_miles"]
            if can_finish[i] and leg <= max_range + EPSILON:
                reachable.append((i, station, leg))

        cheaper = None
        if current is not None:
            cheaper = next((item for item in reachable
                            if float(item[1]["price"]) < float(current["price"])), None)
        # Buy just enough for the first cheaper stop, or for the destination.
        if cheaper is not None:
            target = cheaper
            desired = target[2]
        elif current is not None and to_finish <= max_range + EPSILON:
            target = None
            desired = to_finish
        elif reachable:
            # Otherwise fill up and choose the cheapest reachable stop.
            target = min(reachable, key=lambda item: (
                float(item[1]["price"]), -float(item[1]["mile"]), item[2]
            ))
            desired = max_range
        else:
            raise TripPlanningError(
                f"No reachable fuel station after route mile {current_mile:.1f}; "
                f"the {max_range:.0f}-mile range includes estimated station detours."
            )

        if current is not None:
            buy_miles = max(0.0, desired - remaining_range)
            if buy_miles > EPSILON:
                gallons = buy_miles / mpg
                # Round each receipt before adding it to the trip's total cost.
                charge = (Decimal(str(gallons)) * Decimal(str(current["price"]))).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                purchases.append({
                    **{k: current.get(k) for k in (
                        "opis_id", "name", "address", "city", "state", "lat", "lon",
                        "route_lat", "route_lon",
                    )},
                    "mile": float(current["mile"]),
                    "detour_miles": current_detour,
                    "coordinate_source": current.get("coordinate_source", "city_centroid"),
                    "price_per_gallon": float(current["price"]),
                    "gallons": round(gallons, 6),
                    "cost_usd": float(charge),
                    "arrival_fuel_gallons": round(remaining_range / mpg, 6),
                    "departure_fuel_gallons": round((remaining_range + buy_miles) / mpg, 6),
                })
                total_gallons += gallons
                total_cost += charge
                remaining_range += buy_miles

        if target is None:
            traveled += to_finish
            break
        index, current, leg = target
        if leg > remaining_range + EPSILON:
            raise TripPlanningError("No fuel station can be reached with the remaining fuel.")
        remaining_range = max(0.0, remaining_range - leg)
        traveled += leg
        current_mile = float(current["mile"])
        current_detour = current["detour_miles"]

    return {
        "gallons_needed": round(traveled / mpg, 6),
        "gallons_purchased": round(total_gallons, 6),
        "total_cost_usd": float(total_cost),
        "estimated_distance_miles": round(traveled, 6),
        "estimated_detour_miles": round(traveled - distance_miles, 6),
        "fuel_stops": purchases,
    }
