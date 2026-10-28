# Fuel Route Planner

Django REST API for a US driving route and cost-effective fuel purchases. Uses the supplied OPIS price file and free Nominatim/OSRM services. No API key is required.

## Run

Requires Python 3.12+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py runserver
```

The supplied located CSV is ready to use. No database migration is needed for the route API. Django is pinned to 6.1.2.

## Request

```bash
curl -X POST http://127.0.0.1:8000/api/route/ \
  -H 'Content-Type: application/json' \
  -d '{"start":"Chicago, IL","finish":"Denver, CO"}'
```

The JSON includes:

| Field | Meaning |
|---|---|
| `distance_miles` | OSRM driving-route distance, before station detours |
| `estimated_distance_miles` | Route plus estimated round-trip detours for selected stops |
| `estimated_detour_miles` | Estimated additional mileage for those detours |
| `gallons_needed` | Fuel consumed on the estimated trip at 10 MPG |
| `gallons_purchased` | Fuel bought during the trip |
| `total_cost_usd` | Sum of station purchase charges, rounded to cents per purchase |
| `fuel_stops` | Ordered purchases: location, route mile, price, gallons, cost and tank levels |
| `route_geojson` | The base route as a GeoJSON LineString |
| `warnings` | Location, distance and cost assumptions |

Each stop has `coordinate_source` (`city_centroid` or `verified`) and `detour_miles` (estimated **one-way** distance off route). Gallons are returned to six decimal places so rounded output can be checked against tank capacity. Money is rounded with decimal half-up arithmetic.

Missing/blank locations, no US match, no road route and no feasible fuel plan return HTTP 400. Unavailable or malformed provider responses return HTTP 502.

## Vehicle and cost assumptions

- Maximum range: **500 miles**; economy: **10 MPG**; capacity: **50 gallons**.
- The trip starts with a full tank. Its acquisition cost is unknown and excluded.
- `total_cost_usd` means **purchases during the trip**, identified by `fuel_cost_basis: "purchases_during_trip"` and `starting_fuel_cost_included: false`.
- A trip of 500 miles or less can therefore need no fuel purchase, despite consuming fuel.
- The planner buys at stations in forward travel order, checks arrival/departure fuel and includes estimated detours on every leg. An infeasible gap is rejected.

## Algorithm and accuracy

The planner prefers the first cheaper reachable station and buys only enough to reach it. If none is cheaper, it fills as needed and prefers the cheapest reachable next stop. A backward reachability check excludes stations with no feasible continuation. This is the standard optimal greedy strategy on a fixed route **without detours**. With station detours it is a cost-conscious heuristic, not a claim of global optimality over every road and station combination.

The original price file has addresses and city names but **no station coordinates**. The bundled located file uses city reference coordinates. These are explicitly marked as estimates, not actual pump locations. Of 7,531 US price rows, 7,516 have city matches; 15 lack a match. Another 620 source rows are outside the supported US states.

Route matching projects stations onto road-geometry segments, scales mile markers to OSRM's distance and keeps alternatives with different access distances. Stations may sit up to 10 straight-line miles off route. Both the outbound and return distances are included in the estimate. Straight-line distance **does not establish road access**: bridges, exits and divided roads may add mileage. Exact station coordinates and routed access legs are needed to guarantee real driving feasibility. The JSON discloses this limitation.

## Offline station preparation

Rebuild the city-based file without calling map APIs:

```bash
python scripts/locate_stations.py
```

The script downloads a city reference only if missing, retains original prices and writes `data/fuel-prices-unmatched.csv` for US rows needing review. It never geocodes stations at request time.

To use externally verified station coordinates, prepare a CSV:

```csv
opis_id,lat,lon
7,36.607931,-95.274736
```

The row above illustrates the **format only**; replace it with verified pump coordinates. Import with:

```bash
python scripts/locate_stations.py --coordinates /absolute/path/verified-stations.csv
```

Verified points take precedence over city matches, including cities missing from the reference. Add `--strict` to include only verified points. This may leave insufficient coverage until the verified file is complete. Do not bulk-geocode the dataset through the public Nominatim service.

## Performance and external calls

- An uncached named trip makes **at most three calls**: two geocoding requests and one OSRM route request. No station-level calls or automatic retries.
- Geocodes, routes and complete plans share a file cache across workers on the same host. Repeated identical requests use zero provider calls while cached.
- Station CSV contents are cached in memory, refreshed when the file changes. Segment matching uses a spatial grid.
- OSRM routes use compact `polyline6` encoding during transfer, then expand to the same full GeoJSON geometry in the API response. No route points are removed. Stations sharing coordinates reuse the same route projection while retaining their individual prices.
- To investigate response time in Postman, open the response **Headers** tab and inspect `Server-Timing`. Durations are in milliseconds: `geocode_start`, `geocode_finish`, `routing`, `matching`, `fuel`, and `total`. A complete plan cache hit reports `cache` and `total`. Provider delays can still make the first request slow; timings cover planning before response rendering and transfer.
- Provider limits still apply: public Nominatim permits at most one request per second per application ([usage policy](https://operations.osmfoundation.org/policies/nominatim/)). The app does not enforce that limit.
- Public routing has no availability guarantee; see the [OSRM usage policy](https://github.com/Project-OSRM/osrm-backend/wiki/Api-usage-policy).

Cache location can be configured with `MAP_CACHE_DIR`. Provider URLs and the identifying `MAP_USER_AGENT` are configured in `config/settings.py`.

## Verify

```bash
python manage.py check
python manage.py test trips
```

Use the example request above to inspect the JSON route, fuel stops and purchase costs.

## Layout

```text
trips/fuel.py                  Forward fuel planning and tank accounting
trips/geo.py                   Segment projection and spatial filtering
trips/services.py              Provider calls, validation and cached trip results
trips/stations.py              Validated local price loading
scripts/locate_stations.py     Offline coordinates and unmatched-row report
```
