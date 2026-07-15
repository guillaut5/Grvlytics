"""First-draft performance index: grade- and terrain-adjusted speed per heartbeat.

Both adjustment factors below are rough estimates from a single ride
(bedarieux) and need calibration against more data.
"""
from __future__ import annotations

# speed% gained per 1% of grade when flattening a segment to a "flat-equivalent"
# speed - climbs get inflated, descents get deflated. ~8%/1% is a common cycling
# rule of thumb.
GRADE_ADJUST_K = 8.0

# rolling-resistance/handling penalty by terrain: how much speed the same effort
# loses on rougher ground, relative to route.
TERRAIN_ADJUST = {
    "route": 1.00,
    "piste_cyclable": 1.00,
    "chemin": 1.20,
    "sentier": 1.35,
    "autre": 1.00,
    "hors_reseau": 1.00,
}


def perf_index(speed_kmh: float, grade_pct: float, avg_hr: float | None, terrain: str) -> float | None:
    """Grade- and terrain-adjusted speed per heartbeat - higher means more efficient for the effort."""
    if not avg_hr:
        return None
    adjusted_speed = speed_kmh * (1 + GRADE_ADJUST_K * grade_pct / 100) * TERRAIN_ADJUST.get(terrain, 1.0)
    return adjusted_speed / avg_hr
