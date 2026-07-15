"""Aggregate performance across every ride from the last N months.

Three outputs (see grvlytics.period.sync_period):
  1. data/ride_index.csv - one row per ride: date, name, perf index, Strava link.
  2. data/monthly_terrain.csv - per month x terrain category: volume and perf index.
  3. data/segment_progression.csv - segments ridden more than once, one row per
     effort, to track progression on the exact same stretch of road over time.

Usage: python scripts/analyze_period.py [months] [--min-km N]
"""
import argparse
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from grvlytics.period import sync_period
from grvlytics.strava import get_access_token


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("months", nargs="?", type=float, default=6, help="fenêtre en mois (défaut 6)")
    parser.add_argument("--min-km", type=float, default=0, dest="min_km",
                         help="ignore les sorties plus courtes que ça")
    return parser.parse_args()


def main():
    args = parse_args()
    token = get_access_token()
    ride_df, monthly_df, segment_df = sync_period(token, months=args.months, min_km=args.min_km)
    if ride_df.empty:
        return

    print("\ntoutes les sorties (par date) :")
    print(ride_df[["date", "name", "distance_km", "elevation_gain_m", "perf_index", "terrain_dominant"]].to_string(index=False))

    ranked = ride_df.dropna(subset=["perf_index"]).sort_values("perf_index", ascending=False)
    print("\ntop 10 sorties par indice de perf :")
    print(ranked.head(10)[["date", "name", "distance_km", "perf_index", "terrain_dominant"]].to_string(index=False))

    print("\ntendance mensuelle par terrain :")
    print(monthly_df.to_string(index=False))

    if not segment_df.empty:
        print(f"\n{segment_df['segment_id'].nunique()} segments répétés -> data/segment_progression.csv")
    else:
        print("\naucun segment répété sur la période")


if __name__ == "__main__":
    main()
