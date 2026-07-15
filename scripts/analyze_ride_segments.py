"""List every Strava segment a ride crossed, with terrain type, D+/D-, speed, HR.

Not just starred/favorite segments - every segment Strava detects the ride
passing over. Segments where elapsed_time notably exceeds moving_time (a stop
within the segment, e.g. a red light or a photo break) are flagged PAUSE so
they can be excluded from performance comparisons.

Usage: python scripts/analyze_ride_segments.py "bedarieux" [2026-07-11]
"""
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from grvlytics.perf import perf_index
from grvlytics.strava import find_activity, get_access_token, get_activity_detail, get_streams
from grvlytics.terrain import classify_points, elevation_gain_loss

PAUSE_THRESHOLD_S = 10  # elapsed_time - moving_time above this => flagged as paused


def main():
    if len(sys.argv) < 2:
        print("usage: python scripts/analyze_ride_segments.py <bout de nom> [date AAAA-MM-JJ]")
        sys.exit(1)
    name_contains = sys.argv[1]
    on_date = sys.argv[2] if len(sys.argv) > 2 else None

    token = get_access_token()
    ride = find_activity(token, name_contains, on_date=on_date)
    print(f"{ride['start_date_local'][:16]}  {ride['name']!r}  {ride['distance'] / 1000:.1f} km\n")

    detail = get_activity_detail(token, ride["id"])
    efforts = detail.get("segment_efforts", [])
    if not efforts:
        print("aucun segment traversé")
        return

    streams = get_streams(token, ride["id"])
    latlngs = streams["latlng"]["data"]
    altitudes = streams["altitude"]["data"]
    categories = classify_points([p[0] for p in latlngs], [p[1] for p in latlngs])

    print(f"{len(efforts)} segments traversés\n")
    header = (
        f"{'segment':30s} {'km':>5s} {'D+':>5s} {'D-':>5s} {'pente':>6s} {'vitesse':>9s} "
        f"{'FC':>5s} {'indice':>6s}  {'terrain':14s} {''}"
    )
    print(header)
    for e in efforts:
        seg = e["segment"]
        elapsed, moving = e["elapsed_time"], e["moving_time"]
        paused = (elapsed - moving) > PAUSE_THRESHOLD_S
        speed_kmh = (e["distance"] / 1000) / (moving / 3600) if moving else 0
        gain, loss = elevation_gain_loss(altitudes, e["start_index"], e["end_index"])
        cats = categories[e["start_index"]:e["end_index"]] or [categories[e["start_index"]]]
        terrain = Counter(cats).most_common(1)[0][0]
        avg_hr = e.get("average_heartrate")
        hr = f"{avg_hr:.0f}" if avg_hr else "-"
        index = perf_index(speed_kmh, seg["average_grade"], avg_hr, terrain)
        index_str = f"{index:.2f}" if index is not None else "-"
        flag = "PAUSE" if paused else ""
        print(
            f"{seg['name'][:30]:30s} {e['distance'] / 1000:5.2f} {gain:4.0f}m {loss:4.0f}m "
            f"{seg['average_grade']:5.1f}% {speed_kmh:8.1f}km/h "
            f"{hr:>5s} {index_str:>6s}  {terrain:14s} {flag}"
        )


if __name__ == "__main__":
    main()
