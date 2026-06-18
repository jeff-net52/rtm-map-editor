from __future__ import annotations

import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from rtm_map_editor.geometry import HEIGHT, WIDTH, gps_to_map, map_to_gps
from rtm_map_editor.map_archive import (
    LAYER_LABELS,
    LAYER_STYLES,
    LINE_LAYERS,
    POLYGON_LAYERS,
    REQUIRED_LAYERS,
    MapDocument,
    load_map,
)
from rtm_map_editor.osm_import import bounds_from_center, clean_bounds, fetch_osm_document


class MapEditorApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("RTM Map Editor - module autonome")
        self.geometry("1280x820")
        self.minsize(1024, 680)

        self.doc: MapDocument | None = None
        self.zoom = 1.0
        self.active_layer = tk.StringVar(value="track_main")
        self.tool = tk.StringVar(value="select")
        self.status = tk.StringVar(value="Ouvrez une carte RTM ou GeoJSON pour commencer.")
        self.selected: tuple[str, int] | None = None
        self.drag_handle_index: int | None = None
        self.draft_points: list[tuple[float, float]] = []
        self.item_to_feature: dict[int, tuple[str, int]] = {}

        self._build_ui()
        self._bind_events()

    def _build_ui(self) -> None:
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(self, padding=8)
        toolbar.grid(row=0, column=0, columnspan=2, sticky="ew")
        toolbar.columnconfigure(10, weight=1)

        ttk.Button(toolbar, text="Ouvrir carte", command=self.open_map).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(toolbar, text="Importer OSM", command=self.open_osm_import_dialog).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(toolbar, text="Exporter ZIP RTM", command=self.export_map).grid(row=0, column=2, padx=(0, 14))
        ttk.Button(toolbar, text="Zoom +", command=lambda: self.set_zoom(self.zoom * 1.18)).grid(row=0, column=3, padx=3)
        ttk.Button(toolbar, text="Zoom -", command=lambda: self.set_zoom(self.zoom / 1.18)).grid(row=0, column=4, padx=3)
        ttk.Button(toolbar, text="100%", command=lambda: self.set_zoom(1.0)).grid(row=0, column=5, padx=(3, 14))
        ttk.Label(toolbar, textvariable=self.status).grid(row=0, column=10, sticky="e")

        side = ttk.Frame(self, padding=10)
        side.grid(row=1, column=0, sticky="nsw")
        side.columnconfigure(0, weight=1)

        ttk.Label(side, text="Couche active").grid(row=0, column=0, sticky="w")
        self.layer_combo = ttk.Combobox(
            side,
            textvariable=self.active_layer,
            state="readonly",
            width=28,
            values=[f"{layer} - {LAYER_LABELS[layer]}" for layer in REQUIRED_LAYERS],
        )
        self.layer_combo.grid(row=1, column=0, sticky="ew", pady=(2, 10))
        self.layer_combo.bind("<<ComboboxSelected>>", self._on_layer_combo)

        tools = ttk.LabelFrame(side, text="Outils", padding=8)
        tools.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        ttk.Radiobutton(tools, text="Selection / sommets", variable=self.tool, value="select").grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(tools, text="Ajouter ligne", variable=self.tool, value="draw_line").grid(row=1, column=0, sticky="w")
        ttk.Radiobutton(tools, text="Ajouter surface", variable=self.tool, value="draw_polygon").grid(row=2, column=0, sticky="w")
        ttk.Button(tools, text="Terminer trace", command=self.finish_draft).grid(row=3, column=0, sticky="ew", pady=(8, 2))
        ttk.Button(tools, text="Annuler dernier point", command=self.undo_draft_point).grid(row=4, column=0, sticky="ew", pady=2)

        actions = ttk.LabelFrame(side, text="Edition", padding=8)
        actions.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        ttk.Button(actions, text="Reprendre selection", command=self.clone_selected).grid(row=0, column=0, sticky="ew", pady=2)
        ttk.Button(actions, text="Supprimer selection", command=self.delete_selected).grid(row=1, column=0, sticky="ew", pady=2)
        ttk.Button(actions, text="Recalculer affichage", command=self.redraw).grid(row=2, column=0, sticky="ew", pady=2)

        ttk.Label(side, text="Couches").grid(row=4, column=0, sticky="w")
        self.layer_list = tk.Listbox(side, height=10, width=34, activestyle="none")
        self.layer_list.grid(row=5, column=0, sticky="nsew", pady=(2, 10))
        self.layer_list.bind("<<ListboxSelect>>", self._select_layer_from_list)

        help_text = (
            "Clic: selection ou ajout de point\n"
            "Double-clic: termine le trace\n"
            "Glisser un sommet: deplace\n"
            "Molette: zoom\n"
            "Reprendre selection: copie la forme\n"
            "dans la couche active."
        )
        ttk.Label(side, text=help_text, justify="left").grid(row=6, column=0, sticky="ew")

        canvas_frame = ttk.Frame(self)
        canvas_frame.grid(row=1, column=1, sticky="nsew")
        canvas_frame.columnconfigure(0, weight=1)
        canvas_frame.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(canvas_frame, bg="#07111d", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        x_scroll = ttk.Scrollbar(canvas_frame, orient="horizontal", command=self.canvas.xview)
        y_scroll = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.canvas.yview)
        x_scroll.grid(row=1, column=0, sticky="ew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(xscrollcommand=x_scroll.set, yscrollcommand=y_scroll.set)

        self._refresh_layer_list()
        self._sync_combo_text()

    def _bind_events(self) -> None:
        self.canvas.bind("<Button-1>", self.on_canvas_click)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_release)
        self.canvas.bind("<Double-Button-1>", lambda _event: self.finish_draft())
        self.canvas.bind("<MouseWheel>", self.on_mouse_wheel)
        self.bind("<Delete>", lambda _event: self.delete_selected())
        self.bind("<BackSpace>", lambda _event: self.undo_draft_point())
        self.bind("<Escape>", lambda _event: self.cancel_draft())

    def _on_layer_combo(self, _event: Any = None) -> None:
        value = self.layer_combo.get().split(" - ", 1)[0]
        if value in REQUIRED_LAYERS:
            self.active_layer.set(value)
        self._highlight_active_layer()

    def _sync_combo_text(self) -> None:
        layer = self.active_layer.get()
        self.layer_combo.set(f"{layer} - {LAYER_LABELS[layer]}")

    def _select_layer_from_list(self, _event: Any = None) -> None:
        selection = self.layer_list.curselection()
        if not selection:
            return
        layer = REQUIRED_LAYERS[selection[0]]
        self.active_layer.set(layer)
        self._sync_combo_text()

    def _highlight_active_layer(self) -> None:
        self.layer_list.selection_clear(0, tk.END)
        try:
            self.layer_list.selection_set(REQUIRED_LAYERS.index(self.active_layer.get()))
        except ValueError:
            pass

    def _refresh_layer_list(self) -> None:
        self.layer_list.delete(0, tk.END)
        for layer in REQUIRED_LAYERS:
            count = self.doc.feature_count(layer) if self.doc else 0
            self.layer_list.insert(tk.END, f"{LAYER_LABELS[layer]} ({count})")
        self._highlight_active_layer()

    def open_map(self) -> None:
        path = filedialog.askopenfilename(
            title="Ouvrir une carte",
            filetypes=[
                ("Cartes RTM / GeoJSON", "*.zip *.geojson *.json"),
                ("Archives ZIP", "*.zip"),
                ("GeoJSON", "*.geojson *.json"),
                ("Tous les fichiers", "*.*"),
            ],
        )
        if not path:
            return
        try:
            self.doc = load_map(path)
        except Exception as exc:
            messagebox.showerror("Import carte", str(exc))
            return
        self.selected = None
        self.draft_points = []
        self.zoom = 1.0
        self.status.set(f"Carte chargee: {Path(path).name}")
        self._refresh_layer_list()
        self.redraw()

    def open_osm_import_dialog(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Importer une zone OpenStreetMap")
        dialog.transient(self)
        dialog.resizable(False, False)
        dialog.columnconfigure(1, weight=1)

        default_bounds = self.doc.bounds if self.doc and self.doc.bounds else {"south": 48.3166, "west": 6.0706, "north": 48.3249, "east": 6.0889}
        name_var = tk.StringVar(value="Carte OpenStreetMap")
        center_lat_var = tk.StringVar(value=f"{((default_bounds['south'] + default_bounds['north']) / 2):.6f}")
        center_lon_var = tk.StringVar(value=f"{((default_bounds['west'] + default_bounds['east']) / 2):.6f}")
        radius_var = tk.StringVar(value="900")
        south_var = tk.StringVar(value=f"{default_bounds['south']:.6f}")
        west_var = tk.StringVar(value=f"{default_bounds['west']:.6f}")
        north_var = tk.StringVar(value=f"{default_bounds['north']:.6f}")
        east_var = tk.StringVar(value=f"{default_bounds['east']:.6f}")
        dialog_status = tk.StringVar(value="Definissez une zone, ouvrez OSM si besoin, puis importez.")

        def current_bounds() -> dict[str, float]:
            return clean_bounds({"south": south_var.get(), "west": west_var.get(), "north": north_var.get(), "east": east_var.get()})

        def fill_bounds(bounds: dict[str, float]) -> None:
            south_var.set(f"{bounds['south']:.6f}")
            west_var.set(f"{bounds['west']:.6f}")
            north_var.set(f"{bounds['north']:.6f}")
            east_var.set(f"{bounds['east']:.6f}")
            center_lat_var.set(f"{((bounds['south'] + bounds['north']) / 2):.6f}")
            center_lon_var.set(f"{((bounds['west'] + bounds['east']) / 2):.6f}")

        def apply_center_radius() -> None:
            try:
                fill_bounds(bounds_from_center(float(center_lat_var.get()), float(center_lon_var.get()), float(radius_var.get())))
                dialog_status.set("Zone calculee depuis le centre et le rayon.")
            except Exception as exc:
                messagebox.showerror("Zone OSM", str(exc), parent=dialog)

        def use_current_map() -> None:
            if not self.doc or not self.doc.bounds:
                messagebox.showinfo("Zone OSM", "Aucune carte chargee.", parent=dialog)
                return
            fill_bounds(self.doc.bounds)
            dialog_status.set("Zone reprise depuis la carte ouverte.")

        def use_mirecourt() -> None:
            fill_bounds({"south": 48.3166, "west": 6.0706, "north": 48.3249, "east": 6.0889})
            name_var.set("Circuit de Mirecourt OSM")
            dialog_status.set("Zone Mirecourt chargee.")

        def open_browser() -> None:
            try:
                bounds = current_bounds()
            except Exception as exc:
                messagebox.showerror("Zone OSM", str(exc), parent=dialog)
                return
            lat = (bounds["south"] + bounds["north"]) / 2
            lon = (bounds["west"] + bounds["east"]) / 2
            url = f"https://www.openstreetmap.org/?mlat={lat:.6f}&mlon={lon:.6f}#map=17/{lat:.6f}/{lon:.6f}"
            webbrowser.open(url)

        def import_osm() -> None:
            try:
                bounds = current_bounds()
            except Exception as exc:
                messagebox.showerror("Zone OSM", str(exc), parent=dialog)
                return
            import_button.configure(state=tk.DISABLED)
            dialog_status.set("Import OpenStreetMap en cours...")

            def worker() -> None:
                try:
                    document = fetch_osm_document(name_var.get(), bounds)
                except Exception as exc:
                    self.after(0, lambda: finish_error(exc))
                    return
                self.after(0, lambda: finish_success(document))

            def finish_error(exc: Exception) -> None:
                import_button.configure(state=tk.NORMAL)
                dialog_status.set("Import OpenStreetMap impossible.")
                messagebox.showerror("Import OSM", str(exc), parent=dialog)

            def finish_success(document: MapDocument) -> None:
                self.doc = document
                self.selected = None
                self.draft_points = []
                self.zoom = 1.0
                self.status.set(f"Zone OSM importee: {document.name}")
                self._refresh_layer_list()
                self.redraw()
                dialog.destroy()

            threading.Thread(target=worker, daemon=True).start()

        ttk.Label(dialog, text="Nom de la carte").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 4))
        ttk.Entry(dialog, textvariable=name_var, width=36).grid(row=0, column=1, columnspan=3, sticky="ew", padx=10, pady=(10, 4))

        center_frame = ttk.LabelFrame(dialog, text="Centre et rayon", padding=8)
        center_frame.grid(row=1, column=0, columnspan=4, sticky="ew", padx=10, pady=6)
        ttk.Label(center_frame, text="Latitude").grid(row=0, column=0, sticky="w")
        ttk.Entry(center_frame, textvariable=center_lat_var, width=12).grid(row=0, column=1, padx=5)
        ttk.Label(center_frame, text="Longitude").grid(row=0, column=2, sticky="w")
        ttk.Entry(center_frame, textvariable=center_lon_var, width=12).grid(row=0, column=3, padx=5)
        ttk.Label(center_frame, text="Rayon m").grid(row=0, column=4, sticky="w")
        ttk.Entry(center_frame, textvariable=radius_var, width=8).grid(row=0, column=5, padx=5)
        ttk.Button(center_frame, text="Calculer zone", command=apply_center_radius).grid(row=0, column=6, padx=(8, 0))

        bounds_frame = ttk.LabelFrame(dialog, text="Zone importee", padding=8)
        bounds_frame.grid(row=2, column=0, columnspan=4, sticky="ew", padx=10, pady=6)
        for index, (label, variable) in enumerate([("Sud", south_var), ("Ouest", west_var), ("Nord", north_var), ("Est", east_var)]):
            ttk.Label(bounds_frame, text=label).grid(row=index // 2, column=(index % 2) * 2, sticky="w", pady=2)
            ttk.Entry(bounds_frame, textvariable=variable, width=14).grid(row=index // 2, column=(index % 2) * 2 + 1, padx=5, pady=2)

        actions = ttk.Frame(dialog, padding=(10, 4))
        actions.grid(row=3, column=0, columnspan=4, sticky="ew")
        ttk.Button(actions, text="Zone Mirecourt", command=use_mirecourt).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(actions, text="Depuis carte actuelle", command=use_current_map).grid(row=0, column=1, padx=6)
        ttk.Button(actions, text="Ouvrir OSM", command=open_browser).grid(row=0, column=2, padx=6)
        import_button = ttk.Button(actions, text="Importer zone", command=import_osm)
        import_button.grid(row=0, column=3, padx=(18, 6))
        ttk.Button(actions, text="Annuler", command=dialog.destroy).grid(row=0, column=4, padx=(6, 0))

        ttk.Label(dialog, textvariable=dialog_status).grid(row=4, column=0, columnspan=4, sticky="w", padx=10, pady=(4, 10))
        dialog.grab_set()

    def export_map(self) -> None:
        if not self.doc:
            messagebox.showinfo("Export", "Ouvrez une carte avant d'exporter.")
            return
        default_name = f"{Path(self.doc.name).stem.replace(' ', '_')}_rtm_edited.zip"
        path = filedialog.asksaveasfilename(
            title="Exporter l'archive RTM",
            defaultextension=".zip",
            initialfile=default_name,
            filetypes=[("Archive RTM", "*.zip")],
        )
        if not path:
            return
        try:
            self.doc.export_zip(path)
        except Exception as exc:
            messagebox.showerror("Export", str(exc))
            return
        self.status.set(f"Archive exportee: {path}")
        messagebox.showinfo("Export", "Archive RTM exportee. Import manuel possible dans RTM.")

    def set_zoom(self, value: float) -> None:
        self.zoom = max(0.35, min(4.0, value))
        self.redraw()

    def on_mouse_wheel(self, event: tk.Event) -> None:
        factor = 1.1 if event.delta > 0 else 1 / 1.1
        self.set_zoom(self.zoom * factor)

    def scaled(self, x: float, y: float) -> tuple[float, float]:
        return x * self.zoom, y * self.zoom

    def event_map_point(self, event: tk.Event) -> tuple[float, float]:
        return self.canvas.canvasx(event.x) / self.zoom, self.canvas.canvasy(event.y) / self.zoom

    def redraw(self) -> None:
        self.canvas.delete("all")
        self.item_to_feature.clear()
        self.canvas.configure(scrollregion=(0, 0, WIDTH * self.zoom, HEIGHT * self.zoom))
        self.canvas.create_rectangle(0, 0, WIDTH * self.zoom, HEIGHT * self.zoom, fill="#07111d", outline="")
        if not self.doc:
            self.canvas.create_text(40, 50, anchor="nw", fill="#94a3b8", text="Ouvrez une archive RTM ou GeoJSON.", font=("Segoe UI", 16, "bold"))
            return
        for layer in REQUIRED_LAYERS:
            for index, feature in enumerate(self.doc.layers.get(layer, {}).get("features") or []):
                self.draw_feature(layer, index, feature)
        self.draw_draft()
        self.draw_selection_handles()
        self._refresh_layer_list()

    def draw_feature(self, layer: str, index: int, feature: dict[str, Any]) -> None:
        geometry = feature.get("geometry") or {}
        geometry_type = geometry.get("type")
        coords = geometry.get("coordinates") or []
        style = LAYER_STYLES[layer]
        selected = self.selected == (layer, index)
        width = int(style["width"] * self.zoom) + (2 if selected else 0)
        outline = "#22c55e" if selected else style["stroke"]
        if geometry_type == "LineString":
            item = self.create_line(coords, outline, width, style.get("dash"))
            if item:
                self.item_to_feature[item] = (layer, index)
        elif geometry_type == "MultiLineString":
            for line in coords:
                item = self.create_line(line, outline, width, style.get("dash"))
                if item:
                    self.item_to_feature[item] = (layer, index)
        elif geometry_type == "Polygon":
            for ring in coords:
                item = self.create_polygon(ring, style.get("fill") or "", outline, width)
                if item:
                    self.item_to_feature[item] = (layer, index)
        elif geometry_type == "MultiPolygon":
            for polygon in coords:
                for ring in polygon:
                    item = self.create_polygon(ring, style.get("fill") or "", outline, width)
                    if item:
                        self.item_to_feature[item] = (layer, index)

    def points_to_canvas(self, coordinates: list[list[float]]) -> list[float]:
        if not self.doc:
            return []
        points: list[float] = []
        for lon, lat in coordinates:
            x, y = gps_to_map(float(lat), float(lon), self.doc.ensure_bounds())
            sx, sy = self.scaled(x, y)
            points.extend([sx, sy])
        return points

    def create_line(self, coordinates: list[list[float]], color: str, width: int, dash: Any = None) -> int | None:
        points = self.points_to_canvas(coordinates)
        if len(points) < 4:
            return None
        dash_value = tuple(int(item * self.zoom) for item in dash) if dash else None
        return int(self.canvas.create_line(*points, fill=color, width=max(1, width), capstyle=tk.ROUND, joinstyle=tk.ROUND, dash=dash_value))

    def create_polygon(self, coordinates: list[list[float]], fill: str, outline: str, width: int) -> int | None:
        points = self.points_to_canvas(coordinates)
        if len(points) < 6:
            return None
        return int(self.canvas.create_polygon(*points, fill=fill, outline=outline, width=max(1, width)))

    def on_canvas_click(self, event: tk.Event) -> None:
        if not self.doc:
            return
        clicked = self.canvas.find_withtag("current")
        tags = self.canvas.gettags(clicked[0]) if clicked else ()
        for tag in tags:
            if tag.startswith("handle:"):
                self.drag_handle_index = int(tag.split(":", 1)[1])
                return
        if self.tool.get() == "select":
            if clicked and clicked[0] in self.item_to_feature:
                self.selected = self.item_to_feature[clicked[0]]
                self.active_layer.set(self.selected[0])
                self._sync_combo_text()
                self.status.set(f"Selection: {LAYER_LABELS[self.selected[0]]} #{self.selected[1] + 1}")
            else:
                self.selected = None
            self.redraw()
            return
        x, y = self.event_map_point(event)
        self.draft_points.append((x, y))
        self.status.set(f"Point ajoute ({len(self.draft_points)}). Double-clic ou Terminer trace pour valider.")
        self.redraw()

    def on_canvas_drag(self, event: tk.Event) -> None:
        if self.drag_handle_index is None or not self.doc or not self.selected:
            return
        layer, index = self.selected
        feature = self.doc.layers[layer]["features"][index]
        points = self.editable_feature_points(feature)
        if not points or self.drag_handle_index >= len(points):
            return
        x, y = self.event_map_point(event)
        lat, lon = map_to_gps(x, y, self.doc.ensure_bounds())
        points[self.drag_handle_index] = [round(lon, 8), round(lat, 8)]
        self.write_editable_feature_points(feature, points)
        self.redraw()

    def on_canvas_release(self, _event: tk.Event) -> None:
        self.drag_handle_index = None

    def editable_feature_points(self, feature: dict[str, Any]) -> list[list[float]] | None:
        geometry = feature.get("geometry") or {}
        geometry_type = geometry.get("type")
        coordinates = geometry.get("coordinates") or []
        if geometry_type == "LineString":
            return [list(point[:2]) for point in coordinates]
        if geometry_type == "Polygon" and coordinates:
            ring = [list(point[:2]) for point in coordinates[0]]
            if len(ring) > 1 and ring[0] == ring[-1]:
                ring = ring[:-1]
            return ring
        return None

    def write_editable_feature_points(self, feature: dict[str, Any], points: list[list[float]]) -> None:
        geometry = feature.get("geometry") or {}
        if geometry.get("type") == "LineString":
            geometry["coordinates"] = points
        elif geometry.get("type") == "Polygon":
            ring = list(points)
            if ring and ring[0] != ring[-1]:
                ring.append(list(ring[0]))
            geometry["coordinates"] = [ring]

    def draw_selection_handles(self) -> None:
        if not self.doc or not self.selected:
            return
        layer, index = self.selected
        feature = self.doc.layers[layer]["features"][index]
        points = self.editable_feature_points(feature)
        if not points:
            return
        for handle_index, (lon, lat) in enumerate(points):
            x, y = gps_to_map(float(lat), float(lon), self.doc.ensure_bounds())
            sx, sy = self.scaled(x, y)
            radius = max(5, int(6 * self.zoom))
            self.canvas.create_oval(
                sx - radius,
                sy - radius,
                sx + radius,
                sy + radius,
                fill="#020617",
                outline="#f8fafc",
                width=2,
                tags=(f"handle:{handle_index}",),
            )

    def draw_draft(self) -> None:
        if not self.draft_points:
            return
        scaled = []
        for x, y in self.draft_points:
            sx, sy = self.scaled(x, y)
            scaled.extend([sx, sy])
        if len(scaled) >= 4:
            self.canvas.create_line(*scaled, fill="#22c55e", width=max(3, int(4 * self.zoom)), dash=(8, 6), capstyle=tk.ROUND)
        for x, y in self.draft_points:
            sx, sy = self.scaled(x, y)
            self.canvas.create_oval(sx - 5, sy - 5, sx + 5, sy + 5, fill="#22c55e", outline="#ffffff")

    def finish_draft(self) -> None:
        if not self.doc or not self.draft_points:
            return
        layer = self.active_layer.get()
        tool = self.tool.get()
        if tool == "draw_line":
            if layer not in LINE_LAYERS:
                messagebox.showinfo("Trace", "Choisissez une couche ligne: piste, pit-lane, voies ou limites.")
                return
            if len(self.draft_points) < 2:
                return
            coordinates = self.draft_to_lonlat()
            self.doc.add_feature(layer, "LineString", coordinates)
        elif tool == "draw_polygon":
            if layer not in POLYGON_LAYERS:
                messagebox.showinfo("Trace", "Choisissez une couche surface: vegetation, batiments ou parking.")
                return
            if len(self.draft_points) < 3:
                return
            coordinates = self.draft_to_lonlat()
            if coordinates[0] != coordinates[-1]:
                coordinates.append(coordinates[0])
            self.doc.add_feature(layer, "Polygon", [coordinates])
        self.draft_points = []
        self.selected = (layer, self.doc.feature_count(layer) - 1)
        self.status.set(f"Objet ajoute dans {LAYER_LABELS[layer]}.")
        self.redraw()

    def draft_to_lonlat(self) -> list[list[float]]:
        if not self.doc:
            return []
        coordinates = []
        for x, y in self.draft_points:
            lat, lon = map_to_gps(x, y, self.doc.ensure_bounds())
            coordinates.append([round(lon, 8), round(lat, 8)])
        return coordinates

    def undo_draft_point(self) -> None:
        if self.draft_points:
            self.draft_points.pop()
            self.redraw()

    def cancel_draft(self) -> None:
        self.draft_points = []
        self.drag_handle_index = None
        self.redraw()

    def clone_selected(self) -> None:
        if not self.doc or not self.selected:
            messagebox.showinfo("Reprendre selection", "Selectionnez d'abord une ligne ou une surface.")
            return
        source_layer, source_index = self.selected
        target_layer = self.active_layer.get()
        try:
            self.doc.clone_feature_to_layer(source_layer, source_index, target_layer)
        except Exception as exc:
            messagebox.showerror("Reprendre selection", str(exc))
            return
        self.selected = (target_layer, self.doc.feature_count(target_layer) - 1)
        self.status.set(f"Geometrie reprise dans {LAYER_LABELS[target_layer]}.")
        self.redraw()

    def delete_selected(self) -> None:
        if not self.doc or not self.selected:
            return
        layer, index = self.selected
        if not messagebox.askyesno("Suppression", f"Supprimer l'objet #{index + 1} de {LAYER_LABELS[layer]} ?"):
            return
        self.doc.delete_feature(layer, index)
        self.selected = None
        self.status.set("Objet supprime.")
        self.redraw()


def main() -> None:
    app = MapEditorApp()
    app.mainloop()
