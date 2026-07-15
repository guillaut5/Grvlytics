"""Find one Strava ride by name (and optionally date) and break effort down by OSM terrain type.

For each terrain category (route/chemin/sentier/piste_cyclable): distance,
elevation gain, average gradient, average speed, average heart rate.

Usage: python scripts/analyze_ride_effort.py "bedarieux" [2026-07-11]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from grvlytics.strava import find_activity, get_access_token, get_streams
from grvlytics.terrain import terrain_effort_breakdown


def main():
    if len(sys.argv) < 2:
        print("usage: python scripts/analyze_ride_effort.py <bout de nom> [date AAAA-MM-JJ]")
        sys.exit(1)
    name_contains = sys.argv[1]
    on_date = sys.argv[2] if len(sys.argv) > 2 else None

    token = get_access_token()
    ride = find_activity(token, name_contains, on_date=on_date)
    print(f"{ride['start_date_local'][:16]}  {ride['name']!r}  {ride['distance'] / 1000:.1f} km\n")

    streams = get_streams(token, ride["id"])
    latlngs = streams["latlng"]["data"]
    heartrate = streams.get("heartrate", {}).get("data")

    rows = terrain_effort_breakdown(
        lats=[p[0] for p in latlngs],
        lngs=[p[1] for p in latlngs],
        distances_m=streams["distance"]["data"],
        altitudes_m=streams["altitude"]["data"],
        grades_pct=streams["grade_smooth"]["data"],
        velocities_ms=streams["velocity_smooth"]["data"],
        heartrates_bpm=heartrate,
    )

    header = f"{'catégorie':16s} {'km':>6s} {'%':>6s} {'D+':>6s} {'pente':>7s} {'vitesse':>9s} {'FC':>5s}"
    print(header)
    for r in rows:
        hr = f"{r['avg_heartrate']:.0f}" if r["avg_heartrate"] else "-"
        print(
            f"{r['category']:16s} {r['distance_km']:6.2f} {r['pct']:5.1f}% "
            f"{r['elevation_gain_m']:5.0f}m {r['avg_grade_pct']:6.1f}% "
            f"{r['avg_speed_kmh']:7.1f}km/h {hr:>5s}"
        )


if __name__ == "__main__":
    main()
