"""Bulk cross-ride aggregation: fetch, classify, and aggregate every ride in a period.

Shared by scripts/analyze_period.py and the `grvl list` CLI command.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Callable

import pandas as pd

from .cache import cached_json
from .perf import perf_index
from .strava import get_activity_detail, get_streams, list_rides_since
from .terrain import classify_points, cluster_tracks, download_graph_for_tracks

PAUSE_THRESHOLD_S = 10  # elapsed_time - moving_time above this => segment effort dropped
MIN_MOVING_SPEED_MS = 0.3
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


def _new_stats() -> dict:
    return {
        "dist_m": 0.0, "elev_gain_m": 0.0, "grade_x_dist": 0.0,
        "moving_time_s": 0.0, "speed_x_time": 0.0, "hr_x_time": 0.0, "hr_time_s": 0.0,
    }


def fetch_ride_data(token: str, ride: dict) -> tuple[dict, dict]:
    streams = cached_json(f"{ride['id']}_streams", lambda: get_streams(token, ride["id"]))
    detail = cached_json(f"{ride['id']}_detail", lambda: get_activity_detail(token, ride["id"]))
    return streams, detail


def sync_period(token: str, months: float = 6, min_km: float = 0, log: Callable[[str], None] = print) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Fetches, classifies and aggregates every ride from the last `months` months.

    Writes data/ride_index.csv, data/monthly_terrain.csv and (if any segment was
    ridden more than once) data/segment_progression.csv, and returns the three
    DataFrames.
    """
    rides = list_rides_since(token, months=months)
    if min_km:
        before = len(rides)
        rides = [r for r in rides if r["distance"] >= min_km * 1000]
        log(f"{before} sorties sur les {months} derniers mois, {len(rides)} après filtre >= {min_km} km")
    else:
        log(f"{len(rides)} sorties sur les {months} derniers mois")
    if not rides:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    log("récupération streams + détails (cache réutilisé si déjà vu)...")
    ride_data = []
    for i, ride in enumerate(rides, 1):
        cached = (DATA_DIR / "cache" / f"{ride['id']}_streams.json").exists()
        log(f"  [{i}/{len(rides)}] {ride['start_date_local'][:10]} {ride['name']!r} "
            f"{'(cache)' if cached else '(appel API...)'}")
        streams, detail = fetch_ride_data(token, ride)
        if not streams.get("latlng", {}).get("data"):
            log("    -> skip: pas de stream GPS")
            continue
        ride_data.append((ride, streams, detail))
    log(f"{len(ride_data)} sorties avec streams GPS exploitables")

    tracks = [([p[0] for p in s["latlng"]["data"]], [p[1] for p in s["latlng"]["data"]]) for _, s, _ in ride_data]
    clusters = cluster_tracks(tracks)
    log(f"{len(clusters)} zone(s) géographique(s) détectée(s)")
    graph_by_ride_index = {}
    for ci, indices in enumerate(clusters, 1):
        log(f"  zone {ci}/{len(clusters)}: {len(indices)} sortie(s), vérification cache OSM régional...")
        cluster_graph = download_graph_for_tracks([tracks[i] for i in indices])
        log(f"  zone {ci}/{len(clusters)}: {len(cluster_graph.edges)} tronçons")
        for i in indices:
            graph_by_ride_index[i] = cluster_graph
    log("classification en cours...")

    monthly = defaultdict(lambda: defaultdict(_new_stats))
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
        ride_stats = defaultdict(_new_stats)

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
            "strava_id": ride["id"],
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
                "segment_id": e["segment"]["id"],
                "segment_name": e["segment"]["name"],
                "date": ride["start_date_local"][:10],
                "speed_kmh": round(speed_kmh, 1),
                "avg_hr": round(avg_hr) if avg_hr else None,
                "perf_index": round(index, 3) if index is not None else None,
                "terrain": terrain,
            })

    ride_df = pd.DataFrame(ride_rows).sort_values("date")

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
    monthly_df = pd.DataFrame(rows).sort_values(["month", "category"]) if rows else pd.DataFrame()

    prog_rows = [
        effort
        for efforts in segment_history.values() if len(efforts) >= 2
        for effort in sorted(efforts, key=lambda x: x["date"])
    ]
    segment_df = pd.DataFrame(prog_rows).sort_values(["segment_name", "date"]) if prog_rows else pd.DataFrame()

    DATA_DIR.mkdir(exist_ok=True)
    ride_df.to_csv(DATA_DIR / "ride_index.csv", index=False)
    monthly_df.to_csv(DATA_DIR / "monthly_terrain.csv", index=False)
    if not segment_df.empty:
        segment_df.to_csv(DATA_DIR / "segment_progression.csv", index=False)

    return ride_df, monthly_df, segment_df
