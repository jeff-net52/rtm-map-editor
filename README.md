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

1. Cliquez sur `Ouvrir carte` et selectionnez une archive.
2. Choisissez une couche active.
3. Utilisez `Selection` pour selectionner un objet et deplacer ses sommets.
4. Utilisez `Ajouter ligne` pour piste, pit-lane, voies ou limites.
5. Utilisez `Ajouter surface` pour vegetation, batiments ou parking.
6. `Reprendre selection` copie la geometrie visuelle selectionnee dans la couche active.
7. `Exporter ZIP RTM` cree une nouvelle archive carte sans l'activer automatiquement dans RTM.

## Publication GitHub

Le module est separe volontairement pour pouvoir devenir un depot public dedie ou un sous-module RTM. Les projets libres verifies sont :

- JOSM : editeur OpenStreetMap open source sous GPL.
- QGIS : SIG desktop open source sous GPL.
- OpenOrienteering Mapper : editeur de cartes open source cross-platform.

Ces outils sont puissants, mais trop larges pour ce besoin RTM immediat. Le module present fournit le flux cible : carte circuit locale, couches RTM, export d'archive RTM.
