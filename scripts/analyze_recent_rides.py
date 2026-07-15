"""Fetch recent short rides from Strava and break down distance by OSM terrain type."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pandas as pd

from grvlytics.strava import get_access_token, get_streams, list_recent_rides
from grvlytics.terrain import terrain_breakdown

MAX_DISTANCE_KM = 50
N_RIDES = 5
OUTPUT_CSV = Path(__file__).resolve().parent.parent / "data" / "terrain_breakdown.csv"


def main():
    token = get_access_token()
    rides = list_recent_rides(token, max_distance_km=MAX_DISTANCE_KM, limit=N_RIDES)
    print(f"{len(rides)} sorties trouvées (< {MAX_DISTANCE_KM} km)\n")

    rows = []
    for ride in rides:
        streams = get_streams(token, ride["id"])
        if "latlng" not in streams or "distance" not in streams:
            print(f"  skip {ride['name']!r}: pas de stream GPS")
            continue
        latlngs = streams["latlng"]["data"]
        distances = streams["distance"]["data"]
        lats = [p[0] for p in latlngs]
        lngs = [p[1] for p in latlngs]

        print(f"  {ride['start_date_local'][:10]}  {ride['name']!r}  {ride['distance'] / 1000:.1f} km")
        totals = terrain_breakdown(lats, lngs, distances)
        total_m = sum(totals.values()) or 1

        row = {"date": ride["start_date_local"][:10], "name": ride["name"], "distance_km": round(ride["distance"] / 1000, 1)}
        for category, meters in totals.items():
            row[category] = round(100 * meters / total_m, 1)
        rows.append(row)

    df = pd.DataFrame(rows).fillna(0)
    print("\n" + df.to_string(index=False))

    OUTPUT_CSV.parent.mkdir(exist_ok=True)
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"\nsauvegardé dans {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
