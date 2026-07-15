"""Find one Strava ride by name (and optionally date) and break its distance down by OSM terrain type.

Usage: python scripts/analyze_single_ride.py "après-midi" [2026-06-30]
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from grvlytics.strava import find_activity, get_access_token, get_latlng_distance_stream
from grvlytics.terrain import terrain_breakdown


def main():
    if len(sys.argv) < 2:
        print("usage: python scripts/analyze_single_ride.py <bout de nom> [date AAAA-MM-JJ]")
        sys.exit(1)
    name_contains = sys.argv[1]
    on_date = sys.argv[2] if len(sys.argv) > 2 else None

    token = get_access_token()
    ride = find_activity(token, name_contains, on_date=on_date)
    print(f"{ride['start_date_local'][:16]}  {ride['name']!r}  {ride['distance'] / 1000:.1f} km")

    streams = get_latlng_distance_stream(token, ride["id"])
    latlngs = streams["latlng"]["data"]
    distances = streams["distance"]["data"]
    lats = [p[0] for p in latlngs]
    lngs = [p[1] for p in latlngs]

    totals = terrain_breakdown(lats, lngs, distances)
    total_m = sum(totals.values()) or 1
    for category, meters in sorted(totals.items(), key=lambda kv: -kv[1]):
        print(f"  {category:16s} {meters / 1000:5.2f} km  ({100 * meters / total_m:.1f}%)")


if __name__ == "__main__":
    main()
