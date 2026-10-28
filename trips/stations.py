"""Read and validate local prices, caching by file identity and modification time."""

import csv
from functools import lru_cache
import math

from django.conf import settings

from .exceptions import TripPlanningError


def load_stations():
    """Reuse parsed prices until the source file changes."""
    path = settings.FUEL_PRICES_PATH
    try:
        stamp = path.stat()
    except FileNotFoundError as exc:
        raise TripPlanningError(
            "Fuel price file is missing. Run python scripts/locate_stations.py."
        ) from exc
    return _read_stations(str(path), stamp.st_mtime_ns, stamp.st_size)


@lru_cache(maxsize=2)
def _read_stations(path, modified_ns, size):
    # The timestamp and size are cache-key inputs, even though parsing uses only path.
    stations = []
    try:
        with open(path, newline="", encoding="utf-8") as handle:
            for line, row in enumerate(csv.DictReader(handle), start=2):
                price, lat, lon = float(row["price"]), float(row["lat"]), float(row["lon"])
                if not (math.isfinite(price) and price > 0
                        and math.isfinite(lat) and -90 <= lat <= 90
                        and math.isfinite(lon) and -180 <= lon <= 180):
                    raise ValueError(f"Invalid price or coordinates on line {line}")
                source = row.get("coordinate_source") or "city_centroid"
                if source not in {"city_centroid", "verified"}:
                    raise ValueError(f"Unknown coordinate source on line {line}")
                stations.append({
                    **{k: row[k] for k in ("opis_id", "name", "address", "city", "state")},
                    "price": price, "lat": lat, "lon": lon, "coordinate_source": source,
                })
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise TripPlanningError(f"Fuel dataset is invalid: {exc}") from exc
    if not stations:
        raise TripPlanningError("Fuel price file is empty.")
    return tuple(stations)
