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
