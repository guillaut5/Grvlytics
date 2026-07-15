"""Tiny disk cache for Strava API responses, keyed by an arbitrary string.

Bulk scripts re-run often while a formula gets tuned; re-fetching the same
activity streams/details from Strava every time is slow and burns rate limit.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "cache"


def cached_json(key: str, fetch_fn: Callable[[], dict]) -> dict:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    data = fetch_fn()
    path.write_text(json.dumps(data), encoding="utf-8")
    return data
