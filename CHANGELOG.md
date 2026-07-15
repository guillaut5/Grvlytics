# Changelog

Toutes les évolutions notables de ce projet sont documentées ici.

Format basé sur [Keep a Changelog](https://keepachangelog.com/fr/1.0.0/),
versionnement selon [SemVer](https://semver.org/lang/fr/).

## [0.1.0] - 2026-07-15

### Ajouté
- Client Strava API v3 (`grvlytics.strava`) : refresh OAuth2, listing des activités, récupération des streams GPS.
- Script d'authentification (`scripts/strava_auth.py`) pour obtenir un refresh token avec le scope `activity:read_all`.
- Classification du terrain par sortie via OpenStreetMap (`grvlytics.terrain`) : snapping des points GPS aux tronçons OSM les plus proches, classification en route / chemin / sentier / piste cyclable à partir des tags `highway`, `surface` et `bicycle`.
- Scripts d'analyse : `scripts/analyze_recent_rides.py` (sorties vélo récentes < 50 km) et `scripts/analyze_single_ride.py` (une sortie par nom/date).
- Validation manuelle sur 4 sorties réelles comparées à Komoot : route, piste cyclable et sentier fiables à ~2-4 points d'écart ; catégorie "chemin" plus bruitée (~6 points), probablement due à l'ambiguïté du tag `highway=path` en OSM.
