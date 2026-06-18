from __future__ import annotations

import copy
import json
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from rtm_map_editor.geometry import HEIGHT, PAD, WIDTH, geojson_bounds, gps_to_map, mercator, transform_coordinates, walk_coordinates

REQUIRED_LAYERS = [
    "track_main",
    "track_karting",
    "pitlane",
    "internal_roads",
    "buildings",
    "parking",
    "vegetation",
    "fences",
]

LINE_LAYERS = {"track_main", "track_karting", "pitlane", "internal_roads", "fences"}
POLYGON_LAYERS = {"buildings", "parking", "vegetation"}

LAYER_LABELS = {
    "track_main": "Piste principale",
    "track_karting": "Karting",
    "pitlane": "Pit-lane",
    "internal_roads": "Voies de circulation",
    "buildings": "Batiments",
    "parking": "Parkings",
    "vegetation": "Vegetation",
    "fences": "Limites utiles",
}

LAYER_STYLES = {
    "vegetation": {"fill": "#244d2a", "stroke": "#2f6b38", "width": 1, "dash": None},
    "parking": {"fill": "#2b3442", "stroke": "#708090", "width": 1, "dash": None},
    "buildings": {"fill": "#3a4351", "stroke": "#d1d5db", "width": 1, "dash": None},
    "internal_roads": {"fill": "", "stroke": "#94a3b8", "width": 3, "dash": None},
    "pitlane": {"fill": "", "stroke": "#38bdf8", "width": 5, "dash": None},
    "track_karting": {"fill": "", "stroke": "#f59e0b", "width": 6, "dash": None},
    "track_main": {"fill": "", "stroke": "#f8fafc", "width": 8, "dash": None},
    "fences": {"fill": "", "stroke": "#f87171", "width": 2, "dash": (6, 5)},
}


def empty_feature_collection() -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": []}


def normalise_geometry(geometry: dict[str, Any] | None) -> dict[str, Any] | None:
    if not geometry:
        return None
    if geometry.get("type") == "LinearRing":
        return {"type": "LineString", "coordinates": geometry.get("coordinates") or []}
    return geometry


def normalise_feature_collection(data: dict[str, Any] | None, layer: str | None = None) -> dict[str, Any]:
    if not data:
        return empty_feature_collection()
    if data.get("type") != "FeatureCollection":
        raise ValueError("GeoJSON non supporte: seul FeatureCollection est accepte")
    features: list[dict[str, Any]] = []
    for index, feature in enumerate(data.get("features") or [], start=1):
        geometry = normalise_geometry(feature.get("geometry"))
        if not geometry:
            continue
        properties = dict(feature.get("properties") or {})
        if layer:
            properties.setdefault("rtm_layer", layer)
        properties.setdefault("rtm_editor_id", f"{layer or 'feature'}_{index}")
        features.append({"type": "Feature", "properties": properties, "geometry": geometry})
    return {"type": "FeatureCollection", "features": features}


def merge_feature_collections(*collections: dict[str, Any] | None) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    for collection in collections:
        features.extend(normalise_feature_collection(collection).get("features") or [])
    return {"type": "FeatureCollection", "features": features}


def read_json_member(archive: zipfile.ZipFile, member: str) -> dict[str, Any] | None:
    try:
        return json.loads(archive.read(member).decode("utf-8"))
    except KeyError:
        return None


def project_geojson(collection: dict[str, Any]) -> dict[str, Any]:
    features = []
    for feature in collection.get("features") or []:
        geometry = feature.get("geometry") or {}
        features.append(
            {
                **feature,
                "geometry": {
                    **geometry,
                    "coordinates": transform_coordinates(geometry.get("coordinates"), mercator),
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def svg_path_for_geometry(geometry: dict[str, Any], bounds: dict[str, float]) -> str:
    def line_path(coordinates: list[Any]) -> str:
        points = []
        for lon, lat in walk_coordinates(coordinates):
            x, y = gps_to_map(lat, lon, bounds)
            points.append(f"{x:.1f} {y:.1f}")
        return "M " + " L ".join(points) if points else ""

    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    if geometry_type == "LineString":
        return line_path(coordinates)
    if geometry_type == "MultiLineString":
        return " ".join(line_path(line) for line in coordinates)
    if geometry_type == "Polygon":
        return " ".join(line_path(ring) + " Z" for ring in coordinates)
    if geometry_type == "MultiPolygon":
        return " ".join(line_path(ring) + " Z" for polygon in coordinates for ring in polygon)
    return ""


def svg_for_layers(layers: dict[str, dict[str, Any]], bounds: dict[str, float]) -> str:
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1400 900">',
        '<rect width="1400" height="900" fill="#07111d"/>',
    ]
    for layer in REQUIRED_LAYERS:
        style = LAYER_STYLES.get(layer, {})
        fill = style.get("fill") or "none"
        stroke = style.get("stroke") or "#ffffff"
        width = style.get("width") or 1
        dash = ' stroke-dasharray="6 5"' if style.get("dash") else ""
        for feature in layers.get(layer, {}).get("features") or []:
            path = svg_path_for_geometry(feature.get("geometry") or {}, bounds)
            if path:
                parts.append(f'<path d="{path}" fill="{fill}" stroke="{stroke}" stroke-width="{width}" opacity="0.92"{dash}/>')
    parts.append("</svg>")
    return "\n".join(parts)


@dataclass
class MapDocument:
    name: str = "Carte RTM"
    source_path: str | None = None
    layers: dict[str, dict[str, Any]] = field(default_factory=lambda: {layer: empty_feature_collection() for layer in REQUIRED_LAYERS})
    bounds: dict[str, float] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def ensure_bounds(self) -> dict[str, float]:
        if not self.bounds:
            self.bounds = geojson_bounds(list(self.layers.values()))
        return self.bounds

    def feature_count(self, layer: str) -> int:
        return len(self.layers.get(layer, {}).get("features") or [])

    def add_feature(self, layer: str, geometry_type: str, coordinates: Any, properties: dict[str, Any] | None = None) -> dict[str, Any]:
        if layer not in REQUIRED_LAYERS:
            raise ValueError(f"Couche inconnue: {layer}")
        feature = {
            "type": "Feature",
            "properties": {
                "rtm_layer": layer,
                "source": "rtm_map_editor",
                "rtm_editor_id": f"{layer}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
                **(properties or {}),
            },
            "geometry": {"type": geometry_type, "coordinates": coordinates},
        }
        self.layers.setdefault(layer, empty_feature_collection()).setdefault("features", []).append(feature)
        self.bounds = geojson_bounds(list(self.layers.values()))
        return feature

    def delete_feature(self, layer: str, index: int) -> None:
        features = self.layers.get(layer, {}).get("features") or []
        if 0 <= index < len(features):
            del features[index]
            if any(collection.get("features") for collection in self.layers.values()):
                self.bounds = geojson_bounds(list(self.layers.values()))

    def clone_feature_to_layer(self, source_layer: str, source_index: int, target_layer: str) -> dict[str, Any]:
        source = self.layers[source_layer]["features"][source_index]
        geometry = copy.deepcopy(source.get("geometry") or {})
        geometry_type = geometry.get("type")
        coordinates = geometry.get("coordinates")
        if target_layer in POLYGON_LAYERS and geometry_type == "LineString":
            ring = list(coordinates or [])
            if ring and ring[0] != ring[-1]:
                ring.append(ring[0])
            geometry_type = "Polygon"
            coordinates = [ring]
        elif target_layer in LINE_LAYERS and geometry_type == "Polygon":
            geometry_type = "LineString"
            coordinates = list((coordinates or [[]])[0])
        return self.add_feature(
            target_layer,
            geometry_type,
            coordinates,
            {"copied_from_layer": source_layer, "copied_from_index": source_index + 1},
        )

    def export_zip_bytes(self, import_source: str | None = None) -> bytes:
        bounds = self.ensure_bounds()
        center = {"lat": (bounds["south"] + bounds["north"]) / 2, "lon": (bounds["west"] + bounds["east"]) / 2}
        root_layers = {layer: normalise_feature_collection(self.layers.get(layer), layer) for layer in REQUIRED_LAYERS}
        all_osm = merge_feature_collections(*root_layers.values())
        reference = {
            "name": self.name,
            "center_gps": center,
            "bounds": bounds,
            "estimated_main_track_length_m": None,
            "available_layers": REQUIRED_LAYERS + ["all_osm_features"],
            "map_scope": "geographic_basemap_only",
            "excluded_operational_objects": ["lights", "race_control_sectors", "incident_zones", "start_finish_line", "reference_points"],
            "operational_storage": "RTM module output, not written to RTM database",
            "import_source": import_source or self.source_path or "RTM Map Editor",
            "exported_at": datetime.now().isoformat(timespec="seconds"),
        }
        policy = {
            "rule": "The map archive contains only the geographic basemap.",
            "not_stored_in_archive": reference["excluded_operational_objects"],
            "storage_target": "RTM Track configuration",
            "managed_by": "RTM Map Editor Module",
        }
        output = BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as target:
            for layer, collection in root_layers.items():
                target.writestr(f"geojson/{layer}.geojson", json.dumps(collection, ensure_ascii=False, indent=2))
                target.writestr(f"geojson_3857/{layer}.geojson", json.dumps(project_geojson(collection), ensure_ascii=False, indent=2))
            target.writestr("geojson/all_osm_features.geojson", json.dumps(all_osm, ensure_ascii=False, indent=2))
            target.writestr("geojson_3857/all_osm_features.geojson", json.dumps(project_geojson(all_osm), ensure_ascii=False, indent=2))
            target.writestr("metadata/track_reference.json", json.dumps(reference, ensure_ascii=False, indent=2))
            target.writestr("metadata/bounds.json", json.dumps({"bounds_wgs84": bounds, "center_gps": center}, ensure_ascii=False, indent=2))
            target.writestr(
                "metadata/projection.json",
                json.dumps({"source": "EPSG:4326 WGS84", "projected": "EPSG:3857 Web Mercator", "projected_folder": "geojson_3857"}, ensure_ascii=False, indent=2),
            )
            target.writestr("metadata/operational_layers_policy.json", json.dumps(policy, ensure_ascii=False, indent=2))
            target.writestr("svg/imported_track_vector.svg", svg_for_layers(root_layers, bounds))
            target.writestr("README.txt", "Archive creee par RTM Map Editor Module. Import manuel requis dans RTM.\n")
        return output.getvalue()

    def export_zip(self, target: str | Path) -> None:
        Path(target).write_bytes(self.export_zip_bytes())


def load_geojson_file(path: Path) -> MapDocument:
    data = json.loads(path.read_text(encoding="utf-8"))
    layer = path.stem if path.stem in REQUIRED_LAYERS else "track_main"
    document = MapDocument(name=path.stem.replace("_", " "), source_path=str(path))
    document.layers[layer] = normalise_feature_collection(data, layer)
    document.bounds = geojson_bounds(list(document.layers.values()))
    return document


def load_zip(path: Path) -> MapDocument:
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        document = MapDocument(name=path.stem.replace("_", " "), source_path=str(path))
        reference = read_json_member(archive, "metadata/track_reference.json")
        if reference:
            document.name = reference.get("name") or document.name
            document.metadata = reference
            document.bounds = reference.get("bounds")
            for layer in REQUIRED_LAYERS:
                document.layers[layer] = normalise_feature_collection(read_json_member(archive, f"geojson/{layer}.geojson"), layer)
            if not document.bounds:
                document.bounds = geojson_bounds(list(document.layers.values()))
            return document

        document.layers["track_main"] = normalise_feature_collection(read_json_member(archive, "track_main.geojson"), "track_main")
        document.layers["track_karting"] = normalise_feature_collection(read_json_member(archive, "track_karting.geojson"), "track_karting")
        document.layers["pitlane"] = normalise_feature_collection(read_json_member(archive, "pitlane.geojson"), "pitlane")
        document.layers["internal_roads"] = normalise_feature_collection(read_json_member(archive, "internal_roads.geojson"), "internal_roads")
        document.layers["buildings"] = normalise_feature_collection(read_json_member(archive, "buildings.geojson"), "buildings")
        document.layers["parking"] = normalise_feature_collection(read_json_member(archive, "parking.geojson"), "parking")
        document.layers["vegetation"] = normalise_feature_collection(read_json_member(archive, "vegetation.geojson"), "vegetation")
        document.layers["fences"] = merge_feature_collections(
            normalise_feature_collection(read_json_member(archive, "fences.geojson"), "fences"),
            normalise_feature_collection(read_json_member(archive, "limit_outer.geojson"), "fences"),
            normalise_feature_collection(read_json_member(archive, "limit_inner.geojson"), "fences"),
        )
        if not any(document.layers[layer]["features"] for layer in REQUIRED_LAYERS):
            geojson_members = [name for name in names if name.lower().endswith(".geojson")]
            for member in geojson_members:
                layer = Path(member).stem
                if layer in REQUIRED_LAYERS:
                    document.layers[layer] = normalise_feature_collection(read_json_member(archive, member), layer)
        document.bounds = geojson_bounds(list(document.layers.values()))
        return document


def load_map(path_value: str | Path) -> MapDocument:
    path = Path(path_value)
    suffix = path.suffix.lower()
    if suffix == ".zip":
        return load_zip(path)
    if suffix in {".geojson", ".json"}:
        return load_geojson_file(path)
    raise ValueError("Format non supporte. Utilisez .zip, .geojson ou .json")
