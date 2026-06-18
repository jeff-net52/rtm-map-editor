from __future__ import annotations

import json
import urllib.parse
import urllib.request
from math import cos, radians
from typing import Any

from rtm_map_editor.map_archive import POLYGON_LAYERS, MapDocument

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "RTM-Map-Editor/0.2"
MAX_BOUNDS_SPAN_DEGREES = 0.2


def clean_bounds(bounds: dict[str, Any]) -> dict[str, float]:
    try:
        cleaned = {
            "south": float(bounds["south"]),
            "west": float(bounds["west"]),
            "north": float(bounds["north"]),
            "east": float(bounds["east"]),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Zone OpenStreetMap invalide") from exc
    if cleaned["south"] >= cleaned["north"] or cleaned["west"] >= cleaned["east"]:
        raise ValueError("Zone OpenStreetMap invalide")
    if cleaned["north"] - cleaned["south"] > MAX_BOUNDS_SPAN_DEGREES or cleaned["east"] - cleaned["west"] > MAX_BOUNDS_SPAN_DEGREES:
        raise ValueError("Zone trop grande pour un import direct")
    return cleaned


def bounds_from_center(lat: float, lon: float, radius_m: float) -> dict[str, float]:
    radius_m = max(50.0, min(6000.0, float(radius_m)))
    delta_lat = radius_m / 111_320
    delta_lon = radius_m / (111_320 * max(0.2, cos(radians(lat))))
    return clean_bounds({"south": lat - delta_lat, "west": lon - delta_lon, "north": lat + delta_lat, "east": lon + delta_lon})


def overpass_query(bounds: dict[str, float]) -> str:
    bbox = f'{bounds["south"]},{bounds["west"]},{bounds["north"]},{bounds["east"]}'
    return f"""
    [out:json][timeout:25];
    (
      way["building"]({bbox});
      way["amenity"="parking"]({bbox});
      way["parking"]({bbox});
      way["landuse"~"forest|grass|meadow|recreation_ground|orchard|vineyard|allotments"]({bbox});
      way["natural"~"wood|scrub|grassland|heath|tree_row"]({bbox});
      way["leisure"~"park|garden|track|sports_centre"]({bbox});
      way["highway"]({bbox});
      way["barrier"]({bbox});
    );
    out geom 4000;
    """


def fetch_osm_document(name: str, bounds: dict[str, Any], timeout_seconds: int = 30) -> MapDocument:
    cleaned = clean_bounds(bounds)
    encoded = urllib.parse.urlencode({"data": overpass_query(cleaned)}).encode("utf-8")
    request = urllib.request.Request(OVERPASS_URL, data=encoded, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return document_from_osm_payload(name, cleaned, payload)


def document_from_osm_payload(name: str, bounds: dict[str, Any], payload: dict[str, Any]) -> MapDocument:
    cleaned = clean_bounds(bounds)
    document = MapDocument(name=(name or "Carte OpenStreetMap").strip() or "Carte OpenStreetMap", source_path="OpenStreetMap / Overpass API", bounds=cleaned)
    document.add_feature("fences", "LineString", bounds_ring(cleaned), {"source": "osm_import_bounds"})
    for element in payload.get("elements") or []:
        if element.get("type") != "way":
            continue
        coordinates = way_coordinates(element)
        if len(coordinates) < 2:
            continue
        tags = element.get("tags") or {}
        layer = layer_for_way(tags)
        if not layer:
            continue
        feature = feature_for_way(layer, coordinates)
        if not feature:
            continue
        document.add_feature(
            layer,
            feature["geometry_type"],
            feature["coordinates"],
            {
                "source": "openstreetmap",
                "osm_id": element.get("id"),
                "osm_tags": tags,
            },
        )
    document.bounds = cleaned
    return document


def bounds_ring(bounds: dict[str, float]) -> list[list[float]]:
    return [
        [bounds["west"], bounds["south"]],
        [bounds["east"], bounds["south"]],
        [bounds["east"], bounds["north"]],
        [bounds["west"], bounds["north"]],
        [bounds["west"], bounds["south"]],
    ]


def way_coordinates(element: dict[str, Any]) -> list[list[float]]:
    coordinates: list[list[float]] = []
    for point in element.get("geometry") or []:
        if "lon" not in point or "lat" not in point:
            continue
        coordinates.append([float(point["lon"]), float(point["lat"])])
    return coordinates


def layer_for_way(tags: dict[str, Any]) -> str | None:
    name = str(tags.get("name") or "").lower()
    highway = str(tags.get("highway") or "").lower()
    leisure = str(tags.get("leisure") or "").lower()
    sport = str(tags.get("sport") or "").lower()
    service = str(tags.get("service") or "").lower()
    barrier = str(tags.get("barrier") or "").lower()

    if tags.get("building"):
        return "buildings"
    if tags.get("amenity") == "parking" or tags.get("parking"):
        return "parking"
    if highway == "raceway" or (leisure == "track" and sport in {"motor", "motorsport", "karting", "auto_racing"}):
        return "track_karting" if "kart" in name or sport == "karting" else "track_main"
    if highway:
        if "pit" in name or "pit" in service:
            return "pitlane"
        return "internal_roads"
    if barrier in {"fence", "wall", "guard_rail", "hedge", "gate"}:
        return "fences"
    if tags.get("landuse") or tags.get("natural") or leisure in {"park", "garden", "sports_centre"}:
        return "vegetation"
    return None


def feature_for_way(layer: str, coordinates: list[list[float]]) -> dict[str, Any] | None:
    if len(coordinates) < 2:
        return None
    closed = len(coordinates) >= 4 and coordinates[0] == coordinates[-1]
    if layer in POLYGON_LAYERS and closed:
        return {"geometry_type": "Polygon", "coordinates": [coordinates]}
    return {"geometry_type": "LineString", "coordinates": coordinates}
