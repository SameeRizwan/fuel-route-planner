"""Load the offline fuel-price dataset into memory once."""

from __future__ import annotations

import csv
from functools import lru_cache

from django.conf import settings

from .exceptions import TripPlanningError


@lru_cache(maxsize=1)
def load_stations() -> tuple[dict, ...]:
    """
    Return every station from FUEL_PRICES_PATH.

    Cached for the process lifetime so each request does not re-read the CSV.
    """
    path = settings.FUEL_PRICES_PATH
    if not path.exists():
        raise TripPlanningError(
            f"Fuel price file not found: {path}. "
            "Run: python scripts/locate_stations.py"
        )

    stations: list[dict] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            stations.append(
                {
                    "opis_id": row["opis_id"],
                    "name": row["name"],
                    "address": row["address"],
                    "city": row["city"],
                    "state": row["state"],
                    "price": float(row["price"]),
                    "lat": float(row["lat"]),
                    "lon": float(row["lon"]),
                }
            )

    if not stations:
        raise TripPlanningError("Fuel price file is empty.")

    return tuple(stations)
