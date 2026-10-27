"""
One-time helper: attach latitude/longitude to fuel stations.

Reads data/fuel-prices.csv (city + state only), matches against a free
US cities coordinate list, and writes data/fuel-prices-located.csv.

Run from the project root:

    python scripts/locate_stations.py

This does not call Nominatim or OSRM. The live API should use the
located CSV only.
"""

from __future__ import annotations

import csv
import re
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_CSV = ROOT / "data" / "fuel-prices.csv"
OUTPUT_CSV = ROOT / "data" / "fuel-prices-located.csv"
CITIES_CSV = ROOT / "data" / "us_cities_ref.csv"

CITIES_URL = (
    "https://raw.githubusercontent.com/kelvins/US-Cities-Database/"
    "main/csv/us_cities.csv"
)

US_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC",
}

# Common abbreviations found in truck-stop city names
CITY_ALIASES = {
    "st ": "saint ",
    "mt ": "mount ",
    "ft ": "fort ",
}


def normalize_city(name: str) -> str:
    text = name.strip().lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    for old, new in CITY_ALIASES.items():
        if text.startswith(old):
            text = new + text[len(old) :]
    return text


def ensure_cities_reference() -> None:
    if CITIES_CSV.exists():
        return
    print(f"Downloading US cities reference → {CITIES_CSV}")
    CITIES_CSV.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(CITIES_URL, CITIES_CSV)


def load_city_index() -> dict[tuple[str, str], tuple[float, float]]:
    """
    Map (normalized city, state code) → (lat, lon).

    When a city appears more than once in a state, average the coordinates.
    """
    buckets: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)

    with CITIES_CSV.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            state = row["STATE_CODE"].strip().upper()
            if state not in US_STATE_CODES:
                continue
            city = normalize_city(row["CITY"])
            buckets[(city, state)].append(
                (float(row["LATITUDE"]), float(row["LONGITUDE"]))
            )

    index: dict[tuple[str, str], tuple[float, float]] = {}
    for key, points in buckets.items():
        lat = sum(p[0] for p in points) / len(points)
        lon = sum(p[1] for p in points) / len(points)
        index[key] = (lat, lon)
    return index


def locate_stations() -> None:
    if not SOURCE_CSV.exists():
        sys.exit(f"Missing source file: {SOURCE_CSV}")

    ensure_cities_reference()
    city_index = load_city_index()

    matched = 0
    skipped_non_us = 0
    unmatched_keys: set[tuple[str, str]] = set()
    output_rows: list[dict] = []

    with SOURCE_CSV.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            state = row["State"].strip().upper()
            city_raw = row["City"].strip()
            city_key = normalize_city(city_raw)

            if state not in US_STATE_CODES:
                skipped_non_us += 1
                continue

            coords = city_index.get((city_key, state))
            if coords is None:
                unmatched_keys.add((city_raw, state))
                continue

            lat, lon = coords
            matched += 1
            output_rows.append(
                {
                    "opis_id": row["OPIS Truckstop ID"].strip(),
                    "name": row["Truckstop Name"].strip(),
                    "address": row["Address"].strip(),
                    "city": city_raw,
                    "state": state,
                    "price": row["Retail Price"].strip(),
                    "lat": f"{lat:.6f}",
                    "lon": f"{lon:.6f}",
                }
            )

    fieldnames = [
        "opis_id",
        "name",
        "address",
        "city",
        "state",
        "price",
        "lat",
        "lon",
    ]
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"US stations matched:   {matched}")
    print(f"Non-US rows skipped:   {skipped_non_us}")
    print(f"Unmatched city+state:  {len(unmatched_keys)}")
    print(f"Wrote {OUTPUT_CSV}")
    if unmatched_keys:
        sample = sorted(unmatched_keys)[:15]
        print("Sample unmatched:")
        for city, state in sample:
            print(f"  - {city}, {state}")


if __name__ == "__main__":
    locate_stations()
