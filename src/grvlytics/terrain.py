"""Classify a GPS track's distance by OSM terrain type via nearest-edge snapping.

Not true HMM map-matching, just per-point nearest-edge lookup. Good enough as a
first pass; revisit if results diverge too much from the Komoot reference.
"""
from __future__ import annotations

import osmnx as ox

ox.settings.useful_tags_way = list(set(ox.settings.useful_tags_way) | {"surface", "bicycle"})

# highway classes that are ambiguous between "route" (paved) and "chemin"
# (unpaved) without looking at `surface` - common on rural French unclassified/
# residential/service ways that are actually dirt/gravel farm roads.
ROAD_HIGHWAYS = {
    "residential", "living_street", "service", "unclassified",
    "tertiary", "tertiary_link", "secondary", "secondary_link",
    "primary", "primary_link", "trunk", "trunk_link",
}
UNPAVED_SURFACES = {
    "unpaved", "gravel", "fine_gravel", "dirt", "ground", "grass",
    "compacted", "mud", "sand", "pebblestone", "earth", "woodchips",
}
MAX_SNAP_DIST_M = 30
BBOX_BUFFER_DEG = 0.003  # ~330m, covers MAX_SNAP_DIST_M with margin


DESIGNATED_CYCLE_VALUES = {"designated", "yes"}


def classify_edge(highway, surface, bicycle=None) -> str:
    hw = highway[0] if isinstance(highway, list) else highway
    sf = surface[0] if isinstance(surface, list) else surface
    bc = bicycle[0] if isinstance(bicycle, list) else bicycle

    if hw == "cycleway":
        return "piste_cyclable"
    if hw in ("path", "footway") and bc in DESIGNATED_CYCLE_VALUES:
        return "piste_cyclable"
    if hw in ("path", "footway", "bridleway", "steps"):
        return "sentier"
    if hw == "track":
        return "chemin"
    if hw in ROAD_HIGHWAYS:
        return "chemin" if sf in UNPAVED_SURFACES else "route"
    return "autre"


def download_graph_for_track(lats: list[float], lngs: list[float]) -> "ox.MultiDiGraph":
    west, east = min(lngs) - BBOX_BUFFER_DEG, max(lngs) + BBOX_BUFFER_DEG
    south, north = min(lats) - BBOX_BUFFER_DEG, max(lats) + BBOX_BUFFER_DEG
    return ox.graph_from_bbox((west, south, east, north), network_type="all", retain_all=True)


def classify_points(lats: list[float], lngs: list[float]) -> list[str]:
    """Returns one terrain category per GPS point, via nearest-OSM-edge snapping."""
    graph = download_graph_for_track(lats, lngs)
    edges = ox.graph_to_gdfs(graph, nodes=False)
    has_surface = "surface" in edges.columns
    has_bicycle = "bicycle" in edges.columns
    nearest, snap_dists = ox.distance.nearest_edges(graph, X=lngs, Y=lats, return_dist=True)

    categories = []
    for i in range(len(lats)):
        if snap_dists[i] > MAX_SNAP_DIST_M:
            categories.append("hors_reseau")
            continue
        u, v, k = nearest[i]
        row = edges.loc[(u, v, k)]
        surface = row["surface"] if has_surface else None
        bicycle = row["bicycle"] if has_bicycle else None
        categories.append(classify_edge(row["highway"], surface, bicycle))
    return categories


def terrain_breakdown(lats: list[float], lngs: list[float], distances_m: list[float]) -> dict[str, float]:
    """Returns {category: meters} by snapping each GPS point to its nearest OSM edge."""
    categories = classify_points(lats, lngs)
    totals: dict[str, float] = {}
    for i in range(len(distances_m) - 1):
        seg_len = distances_m[i + 1] - distances_m[i]
        if seg_len <= 0:
            continue
        totals[categories[i]] = totals.get(categories[i], 0.0) + seg_len
    return totals


# below this speed (m/s) a point is treated as stopped/rolling-to-a-stop, not
# "riding" - keeps traffic-light stops from dragging down avg speed/HR per terrain
MIN_MOVING_SPEED_MS = 0.3


def terrain_effort_breakdown(
    lats: list[float],
    lngs: list[float],
    distances_m: list[float],
    altitudes_m: list[float],
    grades_pct: list[float],
    velocities_ms: list[float],
    heartrates_bpm: list[float] | None = None,
) -> list[dict]:
    """Per terrain category: distance, elevation gain, avg gradient, avg speed, avg heart rate.

    Gradient is distance-weighted; speed and heart rate are moving-time-weighted
    (estimated per segment as seg_dist / velocity_smooth).
    """
    categories = classify_points(lats, lngs)
    stats: dict[str, dict[str, float]] = {}

    for i in range(len(distances_m) - 1):
        seg_dist = distances_m[i + 1] - distances_m[i]
        if seg_dist <= 0:
            continue
        s = stats.setdefault(categories[i], {
            "dist_m": 0.0, "elev_gain_m": 0.0, "grade_x_dist": 0.0,
            "moving_time_s": 0.0, "speed_x_time": 0.0, "hr_x_time": 0.0, "hr_time_s": 0.0,
        })
        s["dist_m"] += seg_dist
        s["grade_x_dist"] += grades_pct[i] * seg_dist

        d_alt = altitudes_m[i + 1] - altitudes_m[i]
        if d_alt > 0:
            s["elev_gain_m"] += d_alt

        v = velocities_ms[i]
        if v and v > MIN_MOVING_SPEED_MS:
            seg_time = seg_dist / v
            s["moving_time_s"] += seg_time
            s["speed_x_time"] += v * seg_time
            if heartrates_bpm and heartrates_bpm[i]:
                s["hr_x_time"] += heartrates_bpm[i] * seg_time
                s["hr_time_s"] += seg_time

    total_dist_m = sum(s["dist_m"] for s in stats.values()) or 1.0
    rows = []
    for category, s in stats.items():
        rows.append({
            "category": category,
            "distance_km": round(s["dist_m"] / 1000, 2),
            "pct": round(100 * s["dist_m"] / total_dist_m, 1),
            "elevation_gain_m": round(s["elev_gain_m"]),
            "avg_grade_pct": round(s["grade_x_dist"] / s["dist_m"], 1) if s["dist_m"] else 0.0,
            "avg_speed_kmh": round(s["speed_x_time"] / s["moving_time_s"] * 3.6, 1) if s["moving_time_s"] else 0.0,
            "avg_heartrate": round(s["hr_x_time"] / s["hr_time_s"]) if s["hr_time_s"] else None,
        })
    return sorted(rows, key=lambda r: -r["distance_km"])
