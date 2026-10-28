"""Project stations onto route segments using a small spatial grid."""

import math
from collections import defaultdict

EARTH_RADIUS_MILES = 3958.7613
GRID_CELL_DEGREES = 0.2
MAX_SEGMENT_MILES = 5
MILES_PER_LATITUDE_DEGREE = 69


def decode_polyline6(encoded):
    """Expand OSRM's compact, six-decimal route into GeoJSON coordinates."""
    coordinates = []
    position = 0
    latitude = longitude = 0
    while position < len(encoded):
        deltas = []
        for _ in range(2):
            value = 0
            # Each character carries five bits; the sixth bit means 'continue'.
            for shift in range(0, 35, 5):
                chunk = ord(encoded[position]) - 63
                position += 1
                if not 0 <= chunk <= 63:
                    raise ValueError("Invalid polyline character")
                value |= (chunk & 31) << shift
                if chunk < 32:
                    break
            else:
                raise ValueError("Invalid polyline coordinate")
            deltas.append(~(value >> 1) if value & 1 else value >> 1)
        latitude += deltas[0]
        longitude += deltas[1]
        # Encoded points use lat/lon order; GeoJSON uses lon/lat order.
        coordinates.append([longitude / 1_000_000, latitude / 1_000_000])
    return coordinates


def haversine_miles(lat1, lon1, lat2, lon2):
    """Return the straight-line distance along the Earth's surface."""
    rlat1, rlon1, rlat2, rlon2 = map(math.radians, (lat1, lon1, lat2, lon2))
    a = (math.sin((rlat2 - rlat1) / 2) ** 2
         + math.cos(rlat1) * math.cos(rlat2) * math.sin((rlon2 - rlon1) / 2) ** 2)
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(min(1, max(0, a))))


def _project_onto_segment(lat, lon, segment):
    """Return the nearest route point and its fraction along a short segment."""
    lon1, lat1, lon2, lat2, _, _ = segment
    # Longitude degrees shrink toward the poles; adjust before projecting.
    cosine = math.cos(math.radians((lat1 + lat2) / 2))
    dx, dy = (lon2 - lon1) * cosine, lat2 - lat1
    ratio = ((lon - lon1) * cosine * dx + (lat - lat1) * dy) / (dx * dx + dy * dy)
    ratio = max(0, min(1, ratio))  # Clamp to the segment's endpoints.
    route_lon = lon1 + (lon2 - lon1) * ratio
    route_lat = lat1 + (lat2 - lat1) * ratio
    return route_lat, route_lon, ratio


def stations_along_route(stations, route_geojson, max_detour_miles,
                         route_distance_miles=None):
    """Attach route mileage and estimated one-way off-route distance.

    Full geometry vertices are preserved. Long segments are subdivided only to
    bound spatial-index work. Mile markers are scaled to OSRM's road distance.
    Proximity does not establish road access; detours remain straight-line estimates.
    """
    coords = route_geojson.get("coordinates") or []
    if len(coords) < 2:
        return []
    cell = GRID_CELL_DEGREES
    grid = defaultdict(list)
    segments = []
    cumulative = 0.0
    for (lon1, lat1), (lon2, lat2) in zip(coords, coords[1:]):
        length = haversine_miles(lat1, lon1, lat2, lon2)
        if not length:
            continue
        count = max(1, math.ceil(length / MAX_SEGMENT_MILES))
        for part in range(count):
            a, b = part / count, (part + 1) / count
            x1, y1 = lon1 + (lon2 - lon1) * a, lat1 + (lat2 - lat1) * a
            x2, y2 = lon1 + (lon2 - lon1) * b, lat1 + (lat2 - lat1) * b
            segment_length = length / count
            index = len(segments)
            segments.append((x1, y1, x2, y2, cumulative, segment_length))
            # Index every grid cell crossed by the segment's bounding box.
            for i in range(math.floor(min(y1, y2) / cell), math.floor(max(y1, y2) / cell) + 1):
                for j in range(math.floor(min(x1, x2) / cell), math.floor(max(x1, x2) / cell) + 1):
                    grid[i, j].append(index)
            cumulative += segment_length
    if not segments:
        return []
    # Geometry measures straight segments; OSRM supplies the road's total distance.
    scale = route_distance_miles / cumulative if route_distance_miles is not None else 1
    lat_pad = max_detour_miles / MILES_PER_LATITUDE_DEGREE + 0.001
    lon_pad = lat_pad / max(0.01, math.cos(math.radians(max(abs(p[1]) for p in coords))))
    min_lat, max_lat = min(p[1] for p in coords) - lat_pad, max(p[1] for p in coords) + lat_pad
    min_lon, max_lon = min(p[0] for p in coords) - lon_pad, max(p[0] for p in coords) + lon_pad
    lat_cells = math.ceil(lat_pad / cell)
    results = []
    matches_by_location = {}
    for station in stations:
        lat, lon = station["lat"], station["lon"]
        if not (min_lat <= lat <= max_lat and min_lon <= lon <= max_lon):
            continue
        # City-based stations often share coordinates. Match the location once,
        # while retaining every station's own identity and price.
        location = (lat, lon)
        if location in matches_by_location:
            closest = matches_by_location[location]
            if closest is not None:
                results.append({**station, **closest})
            continue
        lon_cells = math.ceil(lat_pad / max(0.01, math.cos(math.radians(lat))) / cell)
        i, j = math.floor(lat / cell), math.floor(lon / cell)
        candidates = set()
        for di in range(-lat_cells, lat_cells + 1):
            for dj in range(-lon_cells, lon_cells + 1):
                candidates.update(grid.get((i + di, j + dj), ()))
        closest = None
        closest_distance = max_detour_miles
        for index in sorted(candidates):
            segment = segments[index]
            mile, length = segment[4:]
            route_lat, route_lon, ratio = _project_onto_segment(lat, lon, segment)
            distance = haversine_miles(lat, lon, route_lat, route_lon)
            if distance <= closest_distance:
                closest_distance = distance
                closest = {
                    "mile": (mile + ratio * length) * scale,
                    "detour_miles": distance, "route_lat": route_lat, "route_lon": route_lon,
                }
        matches_by_location[location] = closest
        if closest is not None:
            results.append({**station, **closest})
    return sorted(results, key=lambda s: (s["mile"], s["price"], s.get("opis_id", "")))
