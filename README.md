# Fuel Route Planner

Django API that plans a US driving route, suggests cost-effective fuel stops along the way, and estimates total fuel spend.

## Assignment assumptions

| Setting | Value |
|--------|--------|
| Max vehicle range | 500 miles |
| Fuel economy | 10 miles per gallon |
| Starting tank | Full (that fuel is not charged again) |
| Station placement | Must sit within ~10 miles of the route |

Fuel prices come from the provided OPIS truck-stop CSV. Station coordinates are resolved **offline** from city/state so the live API only calls free map/routing services for the trip path (ideally one route call, plus geocoding for start and finish).

## Stack

- Django 6 + Django REST Framework
- [Nominatim](https://nominatim.openstreetmap.org/) — place → coordinates (US only)
- [OSRM](https://project-osrm.org/) — driving route + GeoJSON line
- Local CSV for fuel prices (no map API for stations)

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py runserver
```

If you only have `data/fuel-prices.csv` (no coordinates), generate the located file once:

```bash
python scripts/locate_stations.py
```

That writes `data/fuel-prices-located.csv`. The running API reads this file only and does not geocode stations.

## API

### `POST /api/route/`

**Request**

```json
{
  "start": "Chicago, IL",
  "finish": "Denver, CO"
}
```

**Response (shape)**

```json
{
  "start": "Chicago, IL",
  "finish": "Denver, CO",
  "distance_miles": 1004.35,
  "duration_seconds": 54012,
  "mpg": 10,
  "max_range_miles": 500,
  "gallons_needed": 100.44,
  "gallons_purchased": 50.44,
  "total_cost_usd": 141.89,
  "fuel_stops": [
    {
      "name": "Example Travel Center",
      "city": "Gretna",
      "state": "NE",
      "mile": 484.0,
      "price_per_gallon": 2.9207,
      "gallons": 5.8,
      "cost_usd": 16.94,
      "lat": 41.13,
      "lon": -96.24
    }
  ],
  "stations_considered": 75,
  "route_geojson": { "type": "LineString", "coordinates": [] },
  "map_url": "https://www.openstreetmap.org/directions?...",
  "start_location": {},
  "finish_location": {}
}
```

**Example**

```bash
curl -X POST http://127.0.0.1:8000/api/route/ \
  -H "Content-Type: application/json" \
  -d '{"start": "Chicago, IL", "finish": "Denver, CO"}'
```

Open `map_url` in a browser to see the route. `route_geojson` can be drawn with any map library (e.g. Leaflet).

## How it works

1. **Geocode** start and finish (Nominatim, US only) — cached.
2. **Route** once with OSRM — cached.
3. **Filter** local fuel stations near the route line.
4. **Plan fuel** with a cheapest-first strategy: start full, never exceed 500 miles between fill-ups, buy from the lowest prices already reachable.

Repeated identical requests reuse cached geocode/route results so the map APIs are not called again.

## Project layout

```text
config/                 Django settings and root URLs
trips/                  API app
  views.py              POST /api/route/
  serializers.py        Request validation
  services.py           Orchestrates geocode → route → fuel
  stations.py           Loads fuel CSV once
  geo.py                Stations along the route
  fuel.py               Cost-effective stop selection
data/
  fuel-prices.csv              Original price list
  fuel-prices-located.csv      Same list + lat/lon (offline)
scripts/locate_stations.py     One-time coordinate helper
```

## Notes

- Both endpoints must resolve to locations in the USA.
- If a stretch of road has no station within 500 miles, the API returns an error.
- `total_cost_usd` is what you pay for gallons bought on the trip (starting full tank is not recharged).
