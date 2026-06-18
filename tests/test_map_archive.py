from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path

from rtm_map_editor.map_archive import MapDocument, load_map
from rtm_map_editor.osm_import import bounds_from_center, document_from_osm_payload


class MapArchiveTests(unittest.TestCase):
    @staticmethod
    def _feature_collection(geometry_type: str, coordinates: list, layer: str) -> dict:
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"rtm_layer": layer},
                    "geometry": {"type": geometry_type, "coordinates": coordinates},
                }
            ],
        }

    def test_simplified_zip_import_and_export(self) -> None:
        outer = [
            [6.078, 48.320],
            [6.082, 48.320],
            [6.082, 48.323],
            [6.078, 48.323],
            [6.078, 48.320],
        ]
        track = [[6.079, 48.321], [6.081, 48.321], [6.081, 48.322]]
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("track_main.geojson", json.dumps(self._feature_collection("LineString", track, "track_main")))
            archive.writestr("vegetation.geojson", json.dumps(self._feature_collection("Polygon", [outer], "vegetation")))
            archive.writestr("limit_outer.geojson", json.dumps(self._feature_collection("LinearRing", outer, "fences")))

        with tempfile.TemporaryDirectory(prefix="rtm_map_editor_") as tmp:
            source = Path(tmp) / "source.zip"
            source.write_bytes(buffer.getvalue())
            document = load_map(source)
            self.assertEqual(document.feature_count("track_main"), 1)
            self.assertEqual(document.feature_count("vegetation"), 1)
            self.assertEqual(document.feature_count("fences"), 1)

            document.add_feature("internal_roads", "LineString", [[6.079, 48.3205], [6.081, 48.3205]])
            target = Path(tmp) / "edited.zip"
            document.export_zip(target)
            with zipfile.ZipFile(target) as exported:
                self.assertIn("metadata/track_reference.json", exported.namelist())
                self.assertIn("geojson/internal_roads.geojson", exported.namelist())
                roads = json.loads(exported.read("geojson/internal_roads.geojson").decode("utf-8"))
                self.assertEqual(len(roads["features"]), 1)

    def test_clone_line_to_polygon_layer_closes_ring(self) -> None:
        document = MapDocument(name="Test")
        document.add_feature("track_main", "LineString", [[6.0, 48.0], [6.1, 48.0], [6.1, 48.1]])
        cloned = document.clone_feature_to_layer("track_main", 0, "vegetation")
        self.assertEqual(cloned["geometry"]["type"], "Polygon")
        ring = cloned["geometry"]["coordinates"][0]
        self.assertEqual(ring[0], ring[-1])

    def test_osm_payload_is_imported_as_rtm_layers(self) -> None:
        bounds = {"south": 48.316, "west": 6.070, "north": 48.325, "east": 6.089}
        payload = {
            "elements": [
                {
                    "type": "way",
                    "id": 1,
                    "tags": {"highway": "raceway", "name": "Circuit"},
                    "geometry": [{"lat": 48.320, "lon": 6.078}, {"lat": 48.321, "lon": 6.080}],
                },
                {
                    "type": "way",
                    "id": 2,
                    "tags": {"building": "yes"},
                    "geometry": [
                        {"lat": 48.320, "lon": 6.078},
                        {"lat": 48.320, "lon": 6.079},
                        {"lat": 48.321, "lon": 6.079},
                        {"lat": 48.320, "lon": 6.078},
                    ],
                },
                {
                    "type": "way",
                    "id": 3,
                    "tags": {"landuse": "grass"},
                    "geometry": [
                        {"lat": 48.322, "lon": 6.080},
                        {"lat": 48.322, "lon": 6.081},
                        {"lat": 48.323, "lon": 6.081},
                        {"lat": 48.322, "lon": 6.080},
                    ],
                },
                {
                    "type": "way",
                    "id": 4,
                    "tags": {"highway": "service", "name": "Pit lane"},
                    "geometry": [{"lat": 48.321, "lon": 6.081}, {"lat": 48.322, "lon": 6.082}],
                },
            ]
        }
        document = document_from_osm_payload("OSM test", bounds, payload)

        self.assertEqual(document.feature_count("track_main"), 1)
        self.assertEqual(document.feature_count("buildings"), 1)
        self.assertEqual(document.feature_count("vegetation"), 1)
        self.assertEqual(document.feature_count("pitlane"), 1)
        self.assertEqual(document.feature_count("fences"), 1)
        self.assertEqual(document.bounds, bounds)

    def test_bounds_from_center_creates_valid_small_zone(self) -> None:
        bounds = bounds_from_center(48.32075, 6.07975, 500)

        self.assertLess(bounds["south"], bounds["north"])
        self.assertLess(bounds["west"], bounds["east"])
        self.assertLess(bounds["north"] - bounds["south"], 0.02)


if __name__ == "__main__":
    unittest.main()
