# Grvlytics
Analyse tes sorties Strava en tenant compte du type de terrain — route, gravel, sentier — via map-matching OpenStreetMap

## Installation

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .
```

Puis copie `.env.example` en `.env` et renseigne tes identifiants Strava (voir `scripts/strava_auth.py`).

## CLI : `grvl`

```powershell
# sorties des 6 derniers mois : fetch + classification + indice de perf
# (--offline pour relire data/ride_index.csv sans rappeler Strava)
grvl list --months 6 --min-km 20 --sort idx --top 10
grvl list --grep bedarieux --offline

# terrain + effort (D+, pente, vitesse, FC) d'une sortie - par ID Strava ou bout de nom
grvl show 19279520093
grvl show "après-midi" 2026-06-30

# tous les segments Strava traversés (pas seulement les favoris), avec indice
# de performance ajusté pente + terrain, et détection des pauses internes
grvl segments bedarieux

# progression dans le temps sur un segment repris plusieurs fois
grvl progress "col de la merquière"

# inspecte ou vide le cache régional OpenStreetMap
grvl graph
grvl graph --refresh
```

Le premier `grvl list`/`show`/`segments` sur une nouvelle zone géographique télécharge le
graphe OpenStreetMap correspondant (peut prendre une à quelques minutes selon l'étendue).
Ce graphe est ensuite persisté dans `data/osm_cache/` : tant qu'une sortie reste dans une
zone déjà couverte, aucun nouvel appel réseau n'est fait, même si l'ensemble de sorties
demandé change (nouveau filtre, nouvelle sortie ajoutée).

## Scripts (sans passer par le CLI)

```powershell
.venv\Scripts\python.exe scripts\analyze_period.py 6 --min-km 20
.venv\Scripts\python.exe scripts\analyze_single_ride.py "bedarieux"
.venv\Scripts\python.exe scripts\analyze_ride_effort.py "bedarieux"
.venv\Scripts\python.exe scripts\analyze_ride_segments.py "bedarieux"
```
