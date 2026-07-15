"""Minimal Strava API v3 client: token refresh, activity listing, GPS streams."""
from __future__ import annotations

import os

import requests
from dotenv import load_dotenv

load_dotenv()

API_BASE = "https://www.strava.com/api/v3"

RIDE_SPORT_TYPES = {"Ride", "GravelRide", "MountainBikeRide"}


def get_access_token() -> str:
    resp = requests.post(
        "https://www.strava.com/oauth/token",
        data={
            "client_id": os.environ["STRAVA_CLIENT_ID"],
            "client_secret": os.environ["STRAVA_CLIENT_SECRET"],
            "refresh_token": os.environ["STRAVA_REFRESH_TOKEN"],
            "grant_type": "refresh_token",
        },
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def iter_activities(access_token: str, per_page: int = 50, max_pages: int = 10):
    """Yields all activities, newest first, across pages."""
    headers = {"Authorization": f"Bearer {access_token}"}
    for page in range(1, max_pages + 1):
        resp = requests.get(
            f"{API_BASE}/athlete/activities",
            headers=headers,
            params={"page": page, "per_page": per_page},
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            return
        yield from batch


def list_recent_rides(access_token: str, max_distance_km: float = 50, limit: int = 10, per_page: int = 50) -> list[dict]:
    """Most recent Ride/Gravel/MTB activities under max_distance_km, newest first."""
    rides = []
    for act in iter_activities(access_token, per_page=per_page, max_pages=5):
        if act.get("sport_type") in RIDE_SPORT_TYPES and act["distance"] <= max_distance_km * 1000:
            rides.append(act)
        if len(rides) >= limit:
            break
    return rides


def find_activity(access_token: str, name_contains: str, on_date: str | None = None, max_pages: int = 10) -> dict:
    """First activity (newest first) whose name contains name_contains (case-insensitive).

    on_date, if given, is an ISO date string ("2026-06-30") matched against start_date_local.
    """
    for act in iter_activities(access_token, max_pages=max_pages):
        if name_contains.lower() not in act["name"].lower():
            continue
        if on_date and not act["start_date_local"].startswith(on_date):
            continue
        return act
    raise ValueError(f"aucune activité ne contient {name_contains!r}" + (f" le {on_date}" if on_date else ""))


def get_activity_detail(access_token: str, activity_id: int, include_all_efforts: bool = True) -> dict:
    """Detailed activity, including segment_efforts for every segment the ride crossed."""
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = requests.get(
        f"{API_BASE}/activities/{activity_id}",
        headers=headers,
        params={"include_all_efforts": str(include_all_efforts).lower()},
    )
    resp.raise_for_status()
    return resp.json()


EFFORT_STREAM_KEYS = "latlng,distance,altitude,grade_smooth,velocity_smooth,heartrate"


def get_streams(access_token: str, activity_id: int, keys: str = EFFORT_STREAM_KEYS) -> dict:
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = requests.get(
        f"{API_BASE}/activities/{activity_id}/streams",
        headers=headers,
        params={"keys": keys, "key_by_type": "true"},
    )
    resp.raise_for_status()
    return resp.json()
