from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path

from rtm_map_editor.map_archive import MapDocument, load_map


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


if __name__ == "__main__":
    unittest.main()
