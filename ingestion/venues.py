"""Geocode the venue reference seed with OpenStreetMap Nominatim.

Results are cached in data/bronze/geocode_cache.json so we hit Nominatim once
per query (their usage policy: max 1 request/second, identify yourself).
Manual overrides in transform/seeds/venue_geocode_overrides.csv win.

Usage:  uv run python -m ingestion.venues
"""

from __future__ import annotations

import json
import time

import pandas as pd

from ingestion.common import BRONZE, SEEDS, get_json, write_bronze

CACHE = BRONZE / "geocode_cache.json"
NOMINATIM = "https://nominatim.openstreetmap.org/search"


def geocode(query: str, cache: dict) -> dict | None:
    if query in cache:
        return cache[query]
    time.sleep(1.1)
    hits = get_json(NOMINATIM, params={"q": query, "format": "jsonv2", "limit": 1,
                                       "countrycodes": "us"})
    cache[query] = hits[0] if hits else None
    return cache[query]


def main() -> None:
    ref = pd.read_csv(SEEDS / "venue_reference.csv")
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    rows = []
    try:
        for q in ref.geocode_query.unique():
            hit = geocode(q, cache)
            rows.append({"geocode_query": q,
                         "lat": float(hit["lat"]) if hit else None,
                         "lon": float(hit["lon"]) if hit else None,
                         "osm_display_name": hit["display_name"] if hit else None,
                         "geocode_source": "nominatim" if hit else None})
    finally:
        CACHE.write_text(json.dumps(cache, indent=1))

    geo = pd.DataFrame(rows)
    overrides_path = SEEDS / "venue_geocode_overrides.csv"
    if overrides_path.exists():
        ov = pd.read_csv(overrides_path).assign(geocode_source="manual_override")
        geo = geo.set_index("geocode_query")
        geo.update(ov.set_index("geocode_query"))
        geo = geo.reset_index()

    venues = ref.merge(geo, on="geocode_query", how="left")
    missing = venues[venues.lat.isna()]
    if len(missing):
        print("NOT GEOCODED (add to venue_geocode_overrides.csv):")
        print(missing[["venue_label", "geocode_query"]].to_string(index=False))
    write_bronze(venues, "venues")
    print(f"geocoded {venues.lat.notna().sum()}/{len(venues)} venue labels")


if __name__ == "__main__":
    main()
