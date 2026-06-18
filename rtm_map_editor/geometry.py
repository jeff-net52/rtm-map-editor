from __future__ import annotations

from math import atan, exp, log, pi, tan
from typing import Any, Callable

WIDTH = 1400
HEIGHT = 900
PAD = 40
EARTH_RADIUS_M = 6378137


def mercator(lon: float, lat: float) -> tuple[float, float]:
    x = EARTH_RADIUS_M * lon * pi / 180
    y = EARTH_RADIUS_M * log(tan(pi / 4 + (lat * pi / 180) / 2))
    return x, y


def inverse_mercator(x: float, y: float) -> tuple[float, float]:
    lon = (x / EARTH_RADIUS_M) * 180 / pi
    lat = (2 * atan(exp(y / EARTH_RADIUS_M)) - pi / 2) * 180 / pi
    return lon, lat


def gps_to_map(lat: float, lon: float, bounds: dict[str, float]) -> tuple[float, float]:
    west_south = mercator(bounds["west"], bounds["south"])
    east_north = mercator(bounds["east"], bounds["north"])
    point = mercator(lon, lat)
    x = PAD + ((point[0] - west_south[0]) / (east_north[0] - west_south[0])) * (WIDTH - PAD * 2)
    y = HEIGHT - PAD - ((point[1] - west_south[1]) / (east_north[1] - west_south[1])) * (HEIGHT - PAD * 2)
    return x, y


def map_to_gps(x: float, y: float, bounds: dict[str, float]) -> tuple[float, float]:
    west_south = mercator(bounds["west"], bounds["south"])
    east_north = mercator(bounds["east"], bounds["north"])
    ratio_x = (x - PAD) / (WIDTH - PAD * 2)
    ratio_y = (HEIGHT - PAD - y) / (HEIGHT - PAD * 2)
    projected_x = west_south[0] + ratio_x * (east_north[0] - west_south[0])
    projected_y = west_south[1] + ratio_y * (east_north[1] - west_south[1])
    lon, lat = inverse_mercator(projected_x, projected_y)
    return lat, lon


def walk_coordinates(value: Any) -> list[tuple[float, float]]:
    if not isinstance(value, list):
        return []
    if len(value) >= 2 and all(isinstance(item, (int, float)) for item in value[:2]):
        return [(float(value[0]), float(value[1]))]
    points: list[tuple[float, float]] = []
    for item in value:
        points.extend(walk_coordinates(item))
    return points


def transform_coordinates(value: Any, transform: Callable[[float, float], tuple[float, float]]) -> Any:
    if not isinstance(value, list):
        return value
    if len(value) >= 2 and all(isinstance(item, (int, float)) for item in value[:2]):
        x, y = transform(float(value[0]), float(value[1]))
        return [x, y] + value[2:]
    return [transform_coordinates(item, transform) for item in value]


def geojson_bounds(collections: list[dict[str, Any]]) -> dict[str, float]:
    points: list[tuple[float, float]] = []
    for collection in collections:
        for feature in collection.get("features") or []:
            points.extend(walk_coordinates((feature.get("geometry") or {}).get("coordinates")))
    if not points:
        raise ValueError("La carte ne contient aucune coordonnee exploitable")
    lons = [point[0] for point in points]
    lats = [point[1] for point in points]
    return {"south": min(lats), "west": min(lons), "north": max(lats), "east": max(lons)}
