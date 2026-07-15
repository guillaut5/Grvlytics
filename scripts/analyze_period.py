"""Aggregate performance across every ride from the last N months.

Three outputs:
  1. data/ride_index.csv - one row per ride: date, name, a single perf index
     (distance-weighted average across the terrain categories it crossed),
     and a direct Strava link, to browse past rides and jump back to the
     good ones.
  2. data/monthly_terrain.csv - per month x terrain category: volume (km, D+)
     and average speed/heart rate.
  3. data/segment_progression.csv - for Strava segments ridden more than once
     in the period, one row per effort (date, speed, HR, perf index), so
     progression on the exact same stretch of road can be tracked over time.
     Efforts with an internal pause (elapsed_time >> moving_time) are dropped.

Streams and activity details are cached to data/cache/ (see grvlytics.cache),
so re-running after tweaking the perf formula doesn't re-hit the Strava API.
All rides share a single OSM graph download (grvlytics.terrain.download_graph_for_tracks)
instead of one download per ride.

Usage: python scripts/analyze_period.py [--months N] [--min-km N]
"""
import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pandas as pd

from grvlytics.cache import cached_json
from grvlytics.perf import perf_index
from grvlytics.strava import get_access_token, get_activity_detail, get_streams, list_rides_since
from grvlytics.terrain import classify_points, cluster_tracks, download_graph_for_tracks

PAUSE_THRESHOLD_S = 10
MIN_MOVING_SPEED_MS = 0.3
DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def fetch_ride_data(token, ride):
    streams = cached_json(f"{ride['id']}_streams", lambda: get_streams(token, ride["id"]))
    detail = cached_json(f"{ride['id']}_detail", lambda: get_activity_detail(token, ride["id"]))
    return streams, detail


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("months", nargs="?", type=float, default=6, help="fenêtre en mois (défaut 6)")
    parser.add_argument("--min-km", type=float, default=0, dest="min_km",
                         help="ignore les sorties plus courtes que ça (les trajets courts/commute "
                              "faussent l'indice vers le haut - vitesse facile sur un aller simple "
                              "de quelques km n'est pas comparable à une vraie sortie)")
    return parser.parse_args()


def main():
    args = parse_args()
    months = args.months

    token = get_access_token()
    rides = list_rides_since(token, months=months)
    if args.min_km:
        before = len(rides)
        rides = [r for r in rides if r["distance"] >= args.min_km * 1000]
        print(f"{before} sorties sur les {months} derniers mois, {len(rides)} après filtre >= {args.min_km} km")
    else:
        print(f"{len(rides)} sorties sur les {months} derniers mois")
    if not rides:
        return

    print("récupération streams + détails (cache réutilisé si déjà vu)...")
    ride_data = []
    for i, ride in enumerate(rides, 1):
        cached = (DATA_DIR / "cache" / f"{ride['id']}_streams.json").exists()
        print(f"  [{i}/{len(rides)}] {ride['start_date_local'][:10]} {ride['name']!r} "
              f"{'(cache)' if cached else '(appel API...)'}", flush=True)
        streams, detail = fetch_ride_data(token, ride)
        if not streams.get("latlng", {}).get("data"):
            print(f"    -> skip: pas de stream GPS")
            continue
        ride_data.append((ride, streams, detail))
    print(f"{len(ride_data)} sorties avec streams GPS exploitables\n")

    tracks = [([p[0] for p in s["latlng"]["data"]], [p[1] for p in s["latlng"]["data"]]) for _, s, _ in ride_data]
    clusters = cluster_tracks(tracks)
    print(f"{len(clusters)} zone(s) géographique(s) détectée(s) parmi les sorties -> "
          f"un téléchargement OSM par zone (évite qu'un voyage loin de chez toi ne fasse "
          f"exploser une requête unique)", flush=True)
    graph_by_ride_index = {}
    for ci, indices in enumerate(clusters, 1):
        print(f"  zone {ci}/{len(clusters)}: {len(indices)} sortie(s), téléchargement OSM...", flush=True)
        cluster_graph = download_graph_for_tracks([tracks[i] for i in indices])
        print(f"  zone {ci}/{len(clusters)}: {len(cluster_graph.edges)} tronçons téléchargés", flush=True)
        for i in indices:
            graph_by_ride_index[i] = cluster_graph
    print("classification en cours...\n", flush=True)

    def new_stats():
        return {
            "dist_m": 0.0, "elev_gain_m": 0.0, "grade_x_dist": 0.0,
            "moving_time_s": 0.0, "speed_x_time": 0.0, "hr_x_time": 0.0, "hr_time_s": 0.0,
        }

    monthly = defaultdict(lambda: defaultdict(new_stats))
    segment_history = defaultdict(list)
    ride_rows = []

    for idx, (ride, streams, detail) in enumerate(ride_data):
        month = ride["start_date_local"][:7]
        latlngs = streams["latlng"]["data"]
        lats = [p[0] for p in latlngs]
        lngs = [p[1] for p in latlngs]
        distances = streams["distance"]["data"]
        altitudes = streams["altitude"]["data"]
        grades = streams["grade_smooth"]["data"]
        velocities = streams["velocity_smooth"]["data"]
        heartrates = streams.get("heartrate", {}).get("data")

        categories = classify_points(lats, lngs, graph=graph_by_ride_index[idx])
        ride_stats = defaultdict(new_stats)

        for j in range(len(distances) - 1):
            seg_dist = distances[j + 1] - distances[j]
            if seg_dist <= 0:
                continue
            cat = categories[j]
            for s in (monthly[month][cat], ride_stats[cat]):
                s["dist_m"] += seg_dist
                s["grade_x_dist"] += grades[j] * seg_dist
                d_alt = altitudes[j + 1] - altitudes[j]
                if d_alt > 0:
                    s["elev_gain_m"] += d_alt
                v = velocities[j]
                if v and v > MIN_MOVING_SPEED_MS:
                    t = seg_dist / v
                    s["moving_time_s"] += t
                    s["speed_x_time"] += v * t
                    if heartrates and heartrates[j]:
                        s["hr_x_time"] += heartrates[j] * t
                        s["hr_time_s"] += t

        # ride-level index: distance-weighted average of each terrain category's index
        weighted_sum, weight_total = 0.0, 0.0
        for cat, s in ride_stats.items():
            if s["moving_time_s"] <= 0 or s["hr_time_s"] <= 0 or s["dist_m"] <= 0:
                continue
            avg_speed = s["speed_x_time"] / s["moving_time_s"] * 3.6
            avg_grade = s["grade_x_dist"] / s["dist_m"]
            avg_hr = s["hr_x_time"] / s["hr_time_s"]
            cat_index = perf_index(avg_speed, avg_grade, avg_hr, cat)
            if cat_index is not None:
                weighted_sum += cat_index * s["dist_m"]
                weight_total += s["dist_m"]
        ride_index = weighted_sum / weight_total if weight_total else None
        dominant_terrain = max(ride_stats.items(), key=lambda kv: kv[1]["dist_m"])[0] if ride_stats else None

        ride_rows.append({
            "date": ride["start_date_local"][:10],
            "name": ride["name"],
            "distance_km": round(ride["distance"] / 1000, 1),
            "perf_index": round(ride_index, 3) if ride_index is not None else None,
            "terrain_dominant": dominant_terrain,
            "strava_url": f"https://www.strava.com/activities/{ride['id']}",
        })

        for e in detail.get("segment_efforts", []):
            if (e["elapsed_time"] - e["moving_time"]) > PAUSE_THRESHOLD_S:
                continue
            avg_hr = e.get("average_heartrate")
            moving = e["moving_time"]
            speed_kmh = (e["distance"] / 1000) / (moving / 3600) if moving else 0
            cats = categories[e["start_index"]:e["end_index"]] or [categories[e["start_index"]]]
            terrain = Counter(cats).most_common(1)[0][0]
            index = perf_index(speed_kmh, e["segment"]["average_grade"], avg_hr, terrain)
            segment_history[e["segment"]["id"]].append({
                "segment_name": e["segment"]["name"],
                "date": ride["start_date_local"][:10],
                "speed_kmh": round(speed_kmh, 1),
                "avg_hr": round(avg_hr) if avg_hr else None,
                "perf_index": round(index, 3) if index is not None else None,
                "terrain": terrain,
            })

    ride_df = pd.DataFrame(ride_rows).sort_values("date")
    DATA_DIR.mkdir(exist_ok=True)
    ride_path = DATA_DIR / "ride_index.csv"
    ride_df.to_csv(ride_path, index=False)
    print(f"liste des sorties avec indice -> {ride_path}")
    print("\ntoutes les sorties (par date) :")
    print(ride_df[["date", "name", "distance_km", "perf_index", "terrain_dominant"]].to_string(index=False))
    ranked = ride_df.dropna(subset=["perf_index"]).sort_values("perf_index", ascending=False)
    print("\ntop 10 sorties par indice de perf :")
    print(ranked.head(10)[["date", "name", "distance_km", "perf_index", "terrain_dominant"]].to_string(index=False))

    rows = []
    for month in sorted(monthly):
        for cat, s in monthly[month].items():
            avg_speed = s["speed_x_time"] / s["moving_time_s"] * 3.6 if s["moving_time_s"] else 0
            avg_grade = s["grade_x_dist"] / s["dist_m"] if s["dist_m"] else 0
            avg_hr = s["hr_x_time"] / s["hr_time_s"] if s["hr_time_s"] else None
            rows.append({
                "month": month,
                "category": cat,
                "distance_km": round(s["dist_m"] / 1000, 1),
                "elevation_gain_m": round(s["elev_gain_m"]),
                "avg_grade_pct": round(avg_grade, 1),
                "avg_speed_kmh": round(avg_speed, 1),
                "avg_heartrate": round(avg_hr) if avg_hr else None,
                "perf_index": round(perf_index(avg_speed, avg_grade, avg_hr, cat), 3) if avg_hr else None,
            })
    monthly_df = pd.DataFrame(rows).sort_values(["month", "category"])
    DATA_DIR.mkdir(exist_ok=True)
    monthly_path = DATA_DIR / "monthly_terrain.csv"
    monthly_df.to_csv(monthly_path, index=False)
    print(f"tendance mensuelle par terrain -> {monthly_path}")
    print(monthly_df.to_string(index=False))

    prog_rows = [
        {"segment_id": seg_id, **effort}
        for seg_id, efforts in segment_history.items() if len(efforts) >= 2
        for effort in sorted(efforts, key=lambda x: x["date"])
    ]
    prog_df = pd.DataFrame(prog_rows)
    if not prog_df.empty:
        prog_df = prog_df.sort_values(["segment_name", "date"])
        prog_path = DATA_DIR / "segment_progression.csv"
        prog_df.to_csv(prog_path, index=False)
        print(f"\n{prog_df['segment_id'].nunique()} segments répétés (sur {len(segment_history)} traversés) -> {prog_path}")
    else:
        print("\naucun segment répété sur la période")


if __name__ == "__main__":
    main()
