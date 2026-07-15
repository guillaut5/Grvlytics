"""Classify a GPS track's distance by OSM terrain type via nearest-edge snapping.

Not true HMM map-matching, just per-point nearest-edge lookup. Good enough as a
first pass; revisit if results diverge too much from the Komoot reference.
"""
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


def terrain_breakdown(lats: list[float], lngs: list[float], distances_m: list[float]) -> dict[str, float]:
    """Returns {category: meters} by snapping each GPS point to its nearest OSM edge."""
    graph = download_graph_for_track(lats, lngs)
    edges = ox.graph_to_gdfs(graph, nodes=False)
    has_surface = "surface" in edges.columns
    has_bicycle = "bicycle" in edges.columns
    nearest, snap_dists = ox.distance.nearest_edges(graph, X=lngs, Y=lats, return_dist=True)

    totals: dict[str, float] = {}
    for i in range(len(distances_m) - 1):
        seg_len = distances_m[i + 1] - distances_m[i]
        if seg_len <= 0:
            continue
        if snap_dists[i] > MAX_SNAP_DIST_M:
            category = "hors_reseau"
        else:
            u, v, k = nearest[i]
            row = edges.loc[(u, v, k)]
            surface = row["surface"] if has_surface else None
            bicycle = row["bicycle"] if has_bicycle else None
            category = classify_edge(row["highway"], surface, bicycle)
        totals[category] = totals.get(category, 0.0) + seg_len
    return totals
