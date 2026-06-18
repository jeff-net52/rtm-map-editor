# RTM Map Editor Module

Module autonome Windows pour importer une carte RTM, dessiner ou corriger ses couches, puis exporter une nouvelle archive ZIP compatible RTM.

Ce module ne modifie pas la base RTM, ne change pas `config/default.yaml` et ne touche pas aux fichiers existants du projet principal. Il travaille sur une copie en memoire et n'ecrit un fichier que lorsque vous utilisez l'export.

## Lancement

Depuis PowerShell :

```powershell
.\RTM_Map_Editor_Module\run_map_editor.ps1
```

Le lanceur utilise `.venv` si l'environnement virtuel du projet existe, sinon il appelle `python`.

## Formats importes

- Archive RTM complete contenant `metadata/track_reference.json` et `geojson/*.geojson`.
- Archive ZIP simplifiee contenant des fichiers comme `track_main.geojson`, `pitlane.geojson`, `vegetation.geojson`, `limit_outer.geojson`.
- Fichier `.geojson` ou `.json` direct.

## Couches editees

- `track_main` : piste principale.
- `track_karting` : piste karting.
- `pitlane` : pit-lane.
- `internal_roads` : voies de circulation.
- `buildings` : batiments.
- `parking` : parkings.
- `vegetation` : vegetation.
- `fences` : limites utiles.

## Utilisation

1. Cliquez sur `Ouvrir carte` et selectionnez une archive, ou cliquez sur `Importer OSM`.
2. Pour OpenStreetMap, indiquez un centre/rayon ou une zone sud-ouest-nord-est, puis cliquez sur `Importer zone`.
3. Le bouton `Ouvrir OSM` ouvre la zone dans OpenStreetMap pour controle visuel avant import.
4. Choisissez une couche active.
5. Utilisez `Selection` pour selectionner un objet et deplacer ses sommets.
6. Utilisez `Ajouter ligne` pour piste, pit-lane, voies ou limites.
7. Utilisez `Ajouter surface` pour vegetation, batiments ou parking.
8. `Reprendre selection` copie la geometrie visuelle selectionnee dans la couche active.
9. `Exporter ZIP RTM` cree une nouvelle archive carte sans l'activer automatiquement dans RTM.

## Import OpenStreetMap

L'import OSM utilise l'API Overpass publique pour recuperer les ways presents dans la zone. Les objets sont classes automatiquement :

- `building` vers `buildings`,
- parkings vers `parking`,
- zones naturelles, parcs et surfaces herbeuses vers `vegetation`,
- `highway=raceway` vers `track_main` ou `track_karting`,
- routes de service vers `internal_roads` ou `pitlane` si le nom/service indique une pit-lane,
- barrieres et clotures vers `fences`.

La zone est volontairement limitee pour eviter les imports trop lourds depuis un service public.

## Publication GitHub

Le module est separe volontairement pour pouvoir devenir un depot public dedie ou un sous-module RTM. Les projets libres verifies sont :

- JOSM : editeur OpenStreetMap open source sous GPL.
- QGIS : SIG desktop open source sous GPL.
- OpenOrienteering Mapper : editeur de cartes open source cross-platform.

Ces outils sont puissants, mais trop larges pour ce besoin RTM immediat. Le module present fournit le flux cible : carte circuit locale, couches RTM, export d'archive RTM.
