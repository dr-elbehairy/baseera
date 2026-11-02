"""Small geodesy helpers. PostGIS is not required for the prototype; a 25 m matching radius is well served by
haversine on an indexed lon/lat bounding box."""
from __future__ import annotations

import math

EARTH_M = 6_371_000.0


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_M * math.asin(math.sqrt(a))


def bbox(lon: float, lat: float, radius_m: float) -> tuple[float, float, float, float]:
    dlat = radius_m / 110_540.0
    dlon = radius_m / (111_320.0 * max(math.cos(math.radians(lat)), 1e-6))
    return lon - dlon, lat - dlat, lon + dlon, lat + dlat


def xy_to_lonlat(x_m: float, y_m: float, lon0: float = 46.70, lat0: float = 24.80) -> tuple[float, float]:
    """Local metres (simulator grid) → WGS84 around a Riyadh origin."""
    lat = lat0 + y_m / 110_540.0
    lon = lon0 + x_m / (111_320.0 * math.cos(math.radians(lat0)))
    return round(lon, 7), round(lat, 7)
