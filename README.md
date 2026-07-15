# Grvlytics
Analyse tes sorties Strava en tenant compte du type de terrain — route, gravel, sentier — via map-matching OpenStreetMap

## Installation

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Puis copie `.env.example` en `.env` et renseigne tes identifiants Strava (voir `scripts/strava_auth.py`).

## Scripts

```powershell
# 5 dernières sorties < 50 km : % de distance par type de terrain, sauvegardé en CSV
.venv\Scripts\python.exe scripts\analyze_recent_rides.py

# une sortie précise par (bout de) nom, avec date optionnelle pour désambiguïser
.venv\Scripts\python.exe scripts\analyze_single_ride.py "bedarieux"
.venv\Scripts\python.exe scripts\analyze_single_ride.py "après-midi" 2026-06-30

# effort par type de terrain : D+, pente moyenne, vitesse moyenne, FC moyenne
.venv\Scripts\python.exe scripts\analyze_ride_effort.py "bedarieux"

# tous les segments Strava traversés (pas seulement les favoris), avec indice
# de performance ajusté pente + terrain, et détection des pauses internes
.venv\Scripts\python.exe scripts\analyze_ride_segments.py "bedarieux"
```

Le premier appel sur une nouvelle zone géographique télécharge le graphe OpenStreetMap
correspondant (peut prendre plusieurs minutes sur une grosse sortie) ; les appels suivants
sur la même zone réutilisent le cache local (`cache/`, ignoré par git).
