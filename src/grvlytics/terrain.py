"""Classify a GPS track's distance by OSM terrain type via nearest-edge snapping.

Not true HMM map-matching, just per-point nearest-edge lookup. Good enough as a
first pass; revisit if results diverge too much from the Komoot reference.
"""
from __future__ import annotations

import json
import math
import uuid
from pathlib import Path

import geopandas as gpd
import osmnx as ox
from shapely import wkt as shapely_wkt
from shapely.geometry import LineString

ox.settings.useful_tags_way = list(set(ox.settings.useful_tags_way) | {"surface", "bicycle"})

# persistent regional graph cache, on top of osmnx's own HTTP-level cache: a
# small change to the ride set (a filter, one new ride) changes the query
# polygon and misses osmnx's cache entirely, even though the actual area of
# interest barely moved. Here, a new request is served from disk if a
# previously downloaded region's polygon already covers it - no Overpass call.
OSM_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "osm_cache"
OSM_CACHE_INDEX = OSM_CACHE_DIR / "index.json"


def _load_osm_cache_index() -> list[dict]:
    if OSM_CACHE_INDEX.exists():
        return json.loads(OSM_CACHE_INDEX.read_text(encoding="utf-8"))
    return []


def _save_osm_cache_index(index: list[dict]) -> None:
    OSM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    OSM_CACHE_INDEX.write_text(json.dumps(index), encoding="utf-8")


def osm_cache_status() -> list[dict]:
    """One entry per cached region: file path and covered area in km²."""
    status = []
    for entry in _load_osm_cache_index():
        poly = shapely_wkt.loads(entry["polygon_wkt"])
        gdf = gpd.GeoSeries([poly], crs="EPSG:4326")
        area_km2 = gdf.to_crs(gdf.estimate_utm_crs()).area.iloc[0] / 1e6
        status.append({"path": entry["path"], "area_km2": round(area_km2, 1)})
    return status


def clear_osm_cache() -> None:
    import shutil
    if OSM_CACHE_DIR.exists():
        shutil.rmtree(OSM_CACHE_DIR)

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
TRACK_BUFFER_M = 60  # corridor half-width around the GPS line, covers MAX_SNAP_DIST_M with margin


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


SIMPLIFY_TOLERANCE_M = 15  # dropped before buffering - a GPS track has ~1 point/sec,
# way denser than needed to describe the route's shape, and buffering that many
# vertices blows up the resulting polygon (and the Overpass query built from it)


def _track_corridor(lats: list[float], lngs: list[float], buffer_m: float = TRACK_BUFFER_M):
    """A polygon within buffer_m of the (simplified) GPS line, in EPSG:4326."""
    line = LineString(zip(lngs, lats)) if len(lats) > 1 else None
    if line is None:
        raise ValueError("need at least 2 points to build a corridor")
    gdf = gpd.GeoDataFrame(geometry=[line], crs="EPSG:4326")
    utm_crs = gdf.estimate_utm_crs()
    line_utm = gdf.to_crs(utm_crs).geometry.iloc[0].simplify(SIMPLIFY_TOLERANCE_M)
    corridor_utm = line_utm.buffer(buffer_m, resolution=4)
    return gpd.GeoSeries([corridor_utm], crs=utm_crs).to_crs("EPSG:4326").iloc[0]


def download_graph_for_track(lats: list[float], lngs: list[float], use_cache: bool = True) -> "ox.MultiDiGraph":
    """Downloads only the OSM network within TRACK_BUFFER_M of the GPS line.

    Much smaller than the route's bounding box on loop/winding rides, where the
    bbox can cover a lot of area the ride never goes near. Thin wrapper around
    download_graph_for_tracks so single-ride lookups also hit the persistent
    regional cache.
    """
    return download_graph_for_tracks([(lats, lngs)], use_cache=use_cache)


def download_graph_for_tracks(
    tracks: list[tuple[list[float], list[float]]],
    buffer_m: float = TRACK_BUFFER_M,
    use_cache: bool = True,
) -> "ox.MultiDiGraph":
    """Downloads the OSM network within buffer_m of the union of several GPS lines.

    One Overpass call for a whole batch of rides instead of one per ride - the
    corridors of rides covering the same home turf overlap heavily, so this is
    far cheaper than downloading (and re-downloading) per ride. Only sensible
    for tracks that are geographically close together - see cluster_tracks for
    grouping a mixed batch (e.g. home rides + a couple of trips far away) before
    calling this, otherwise the union's bounding box balloons to cover the gap.

    If use_cache, reuses a previously downloaded region from data/osm_cache/
    when its coverage polygon already contains the requested area - no
    Overpass call at all. Pass use_cache=False to force a fresh download
    (e.g. a "refresh" command).
    """
    corridors = [_track_corridor(lats, lngs, buffer_m) for lats, lngs in tracks if len(lats) > 1]
    union = gpd.GeoSeries(corridors, crs="EPSG:4326").union_all()

    if use_cache:
        for entry in _load_osm_cache_index():
            if shapely_wkt.loads(entry["polygon_wkt"]).contains(union):
                return ox.load_graphml(entry["path"])

    graph = ox.graph_from_polygon(union, network_type="all", retain_all=True)

    if use_cache:
        OSM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        graph_path = OSM_CACHE_DIR / f"{uuid.uuid4().hex}.graphml"
        ox.save_graphml(graph, graph_path)
        index = _load_osm_cache_index()
        index.append({"polygon_wkt": union.wkt, "path": str(graph_path)})
        _save_osm_cache_index(index)

    return graph


def _track_bbox(lats: list[float], lngs: list[float]) -> tuple[float, float, float, float]:
    return min(lats), max(lats), min(lngs), max(lngs)


def _bbox_gap_km(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    """Rough gap between two lat/lng bboxes, ~0 if they overlap."""
    lat1_min, lat1_max, lng1_min, lng1_max = a
    lat2_min, lat2_max, lng2_min, lng2_max = b
    dlat_deg = max(0.0, lat1_min - lat2_max, lat2_min - lat1_max)
    dlng_deg = max(0.0, lng1_min - lng2_max, lng2_min - lng1_max)
    avg_lat = (lat1_min + lat1_max + lat2_min + lat2_max) / 4
    km_per_deg_lat = 111.0
    km_per_deg_lng = 111.0 * math.cos(math.radians(avg_lat))
    return math.hypot(dlat_deg * km_per_deg_lat, dlng_deg * km_per_deg_lng)


def cluster_tracks(tracks: list[tuple[list[float], list[float]]], max_gap_km: float = 20) -> list[list[int]]:
    """Groups track indices by geographic proximity (single-linkage on bbox gap).

    Rides within max_gap_km of any other ride in the group end up in the same
    cluster (transitively), so a chain of overlapping home-turf rides stays
    together even if the two ends are far apart, while a one-off trip far from
    everything else gets its own cluster.
    """
    bboxes = [_track_bbox(lats, lngs) for lats, lngs in tracks]
    n = len(tracks)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        for j in range(i + 1, n):
            if _bbox_gap_km(bboxes[i], bboxes[j]) <= max_gap_km:
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def elevation_gain_loss(altitudes_m: list[float], start_index: int, end_index: int) -> tuple[float, float]:
    gain = loss = 0.0
    for i in range(start_index, min(end_index, len(altitudes_m) - 1)):
        d = altitudes_m[i + 1] - altitudes_m[i]
        if d > 0:
            gain += d
        else:
            loss += -d
    return gain, loss


def classify_points(lats: list[float], lngs: list[float], graph: "ox.MultiDiGraph | None" = None) -> list[str]:
    """Returns one terrain category per GPS point, via nearest-OSM-edge snapping.

    Downloads its own graph if none is given; pass a shared graph (see
    download_graph_for_tracks) when classifying many rides in the same area.
    """
    if graph is None:
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


def terrain_breakdown(lats: list[float], lngs: list[float], distances_m: list[float], graph: "ox.MultiDiGraph | None" = None) -> dict[str, float]:
    """Returns {category: meters} by snapping each GPS point to its nearest OSM edge."""
    categories = classify_points(lats, lngs, graph=graph)
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
    graph: "ox.MultiDiGraph | None" = None,
) -> list[dict]:
    """Per terrain category: distance, elevation gain, avg gradient, avg speed, avg heart rate.

    Gradient is distance-weighted; speed and heart rate are moving-time-weighted
    (estimated per segment as seg_dist / velocity_smooth).
    """
    categories = classify_points(lats, lngs, graph=graph)
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
