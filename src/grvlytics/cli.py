"""grvl - explore Strava rides classified by terrain type.

  grvl list [--months N] [--min-km N] [--sort date|idx] [--top N] [--grep TEXT] [--offline]
  grvl show <id-ou-nom> [date]
  grvl segments <id-ou-nom> [date]
  grvl progress <bout-de-nom-segment>
  grvl graph [--refresh]
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter

import pandas as pd

from .perf import perf_index
from .period import DATA_DIR, sync_period
from .strava import find_activity, get_access_token, get_activity_detail, get_streams
from .terrain import classify_points, clear_osm_cache, elevation_gain_loss, osm_cache_status, terrain_effort_breakdown

PAUSE_THRESHOLD_S = 10


def _resolve_ride(token: str, identifier: str, date: str | None) -> tuple[dict, dict]:
    """Returns (ride-summary-dict, detailed-activity-dict) for a Strava ID or a name/date lookup."""
    if identifier.isdigit():
        detail = get_activity_detail(token, int(identifier))
        ride = {
            "id": detail["id"],
            "name": detail["name"],
            "distance": detail["distance"],
            "start_date_local": detail["start_date_local"],
        }
        return ride, detail
    ride = find_activity(token, identifier, on_date=date)
    detail = get_activity_detail(token, ride["id"])
    return ride, detail


def cmd_list(args):
    ride_path = DATA_DIR / "ride_index.csv"
    if args.offline:
        if not ride_path.exists():
            print("pas de data/ride_index.csv en cache - lance `grvl list` une première fois sans --offline")
            return
        ride_df = pd.read_csv(ride_path)
    else:
        token = get_access_token()
        ride_df, _, _ = sync_period(token, months=args.months, min_km=args.min_km)
    if ride_df.empty:
        print("aucune sortie")
        return

    if args.grep:
        ride_df = ride_df[ride_df["name"].str.contains(args.grep, case=False, na=False)]
        if ride_df.empty:
            print(f"aucune sortie ne contient {args.grep!r}")
            return

    ascending = args.sort != "idx"
    ride_df = ride_df.sort_values("perf_index" if args.sort == "idx" else "date", ascending=ascending, na_position="last")
    if args.top:
        ride_df = ride_df.head(args.top)

    cols = [c for c in ["strava_id", "date", "name", "distance_km", "perf_index", "terrain_dominant"] if c in ride_df.columns]
    print(ride_df[cols].to_string(index=False))


def cmd_show(args):
    token = get_access_token()
    ride, _detail = _resolve_ride(token, args.identifier, args.date)
    streams = get_streams(token, ride["id"])
    latlngs = streams["latlng"]["data"]

    rows = terrain_effort_breakdown(
        lats=[p[0] for p in latlngs],
        lngs=[p[1] for p in latlngs],
        distances_m=streams["distance"]["data"],
        altitudes_m=streams["altitude"]["data"],
        grades_pct=streams["grade_smooth"]["data"],
        velocities_ms=streams["velocity_smooth"]["data"],
        heartrates_bpm=streams.get("heartrate", {}).get("data"),
    )
    print(f"{ride['start_date_local'][:16]}  {ride['name']!r}  {ride['distance'] / 1000:.1f} km")
    print(f"https://www.strava.com/activities/{ride['id']}\n")
    header = f"{'terrain':16s} {'km':>6s} {'%':>6s} {'D+':>6s} {'pente':>7s} {'vitesse':>9s} {'FC':>5s}"
    print(header)
    for r in rows:
        hr = f"{r['avg_heartrate']:.0f}" if r["avg_heartrate"] else "-"
        print(
            f"{r['category']:16s} {r['distance_km']:6.2f} {r['pct']:5.1f}% "
            f"{r['elevation_gain_m']:5.0f}m {r['avg_grade_pct']:6.1f}% "
            f"{r['avg_speed_kmh']:7.1f}km/h {hr:>5s}"
        )


def cmd_segments(args):
    token = get_access_token()
    ride, detail = _resolve_ride(token, args.identifier, args.date)
    efforts = detail.get("segment_efforts", [])
    print(f"{ride['start_date_local'][:16]}  {ride['name']!r}  {ride['distance'] / 1000:.1f} km")
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
        f"{'FC':>5s} {'indice':>6s}  {'terrain':14s}"
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


def cmd_progress(args):
    prog_path = DATA_DIR / "segment_progression.csv"
    if not prog_path.exists():
        print("pas de data/segment_progression.csv - lance `grvl list` d'abord")
        return
    df = pd.read_csv(prog_path)
    matches = df[df["segment_name"].str.contains(args.segment, case=False, na=False)]
    if matches.empty:
        print(f"aucun segment répété ne contient {args.segment!r}")
        return

    for name, group in matches.groupby("segment_name"):
        group = group.sort_values("date")
        print(f"\n{name} - {len(group)} passages")
        print(group[["date", "speed_kmh", "avg_hr", "perf_index"]].to_string(index=False))
        first, last = group.iloc[0], group.iloc[-1]
        if pd.notna(first["perf_index"]) and pd.notna(last["perf_index"]) and first["perf_index"]:
            change = 100 * (last["perf_index"] - first["perf_index"]) / first["perf_index"]
            print(f"-> indice {change:+.0f}% entre le {first['date']} et le {last['date']}")


def cmd_graph(args):
    if args.refresh:
        clear_osm_cache()
        print("cache régional OSM vidé - le prochain `grvl list`/`show`/`segments` retéléchargera")
        return
    status = osm_cache_status()
    if not status:
        print("aucune zone en cache")
        return
    print(f"{len(status)} zone(s) en cache :")
    for entry in status:
        print(f"  {entry['path']}  (~{entry['area_km2']} km²)")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="grvl", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="liste les sorties (fetch+classification incluse, sauf --offline)")
    p_list.add_argument("--months", type=float, default=6)
    p_list.add_argument("--min-km", type=float, default=0, dest="min_km")
    p_list.add_argument("--sort", choices=["date", "idx"], default="date")
    p_list.add_argument("--top", type=int, default=None)
    p_list.add_argument("--grep", default=None)
    p_list.add_argument("--offline", action="store_true", help="relit data/ride_index.csv sans appeler Strava")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="détail terrain/effort d'une sortie")
    p_show.add_argument("identifier", help="ID Strava ou bout de nom")
    p_show.add_argument("date", nargs="?", default=None, help="AAAA-MM-JJ, pour désambiguïser un nom générique")
    p_show.set_defaults(func=cmd_show)

    p_seg = sub.add_parser("segments", help="segments Strava traversés par une sortie, avec indice")
    p_seg.add_argument("identifier", help="ID Strava ou bout de nom")
    p_seg.add_argument("date", nargs="?", default=None)
    p_seg.set_defaults(func=cmd_segments)

    p_prog = sub.add_parser("progress", help="progression sur un segment repris plusieurs fois")
    p_prog.add_argument("segment", help="bout de nom du segment")
    p_prog.set_defaults(func=cmd_progress)

    p_graph = sub.add_parser("graph", help="inspecte ou vide le cache régional OSM")
    p_graph.add_argument("--refresh", action="store_true", help="vide le cache régional")
    p_graph.set_defaults(func=cmd_graph)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
