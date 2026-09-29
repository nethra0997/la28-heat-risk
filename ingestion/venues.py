"""Stage 2A: turn venue names into map coordinates (geocoding).

Input:  transform/seeds/venue_reference.csv   hand-made list of the 49 schedule venue labels
        transform/seeds/venue_geocode_overrides.csv   hand-fixed coordinates where the lookup was wrong
Output: data/bronze/venues.parquet (+ .csv copy) with a lat/lon for every venue

Lookups go to OpenStreetMap's free Nominatim service. Its rules: at most 1 request per
second, and say who you are. We save every answer in a cache file so each place is only
ever looked up once.

Usage:  uv run python -m ingestion.venues
"""

import json
import time
from pathlib import Path

import pandas as pd
import requests

NOMINATIM = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "la28-heat-risk (learning project; github.com/nethra0997/la28-heat-risk)"

SEEDS = Path("transform/seeds")
BRONZE = Path("data/bronze")
CACHE = BRONZE / "geocode_cache.json"


def geocode(query: str, cache: dict) -> dict | None:
    """Look up one place name, e.g. "Dodger Stadium, Los Angeles" -> its best match."""
    if query in cache:  # already asked before: answer from the cache, no web request
        return cache[query]
    time.sleep(1.1)  # stay under Nominatim's 1 request/second limit
    r = requests.get(
        NOMINATIM,
        params={"q": query, "format": "jsonv2", "limit": 1, "countrycodes": "us"},
        headers={"User-Agent": USER_AGENT},
        timeout=60,
    )
    r.raise_for_status()
    hits = r.json()  # a list of matches, best first; empty if nothing was found
    cache[query] = hits[0] if hits else None
    print(f"  looked up: {query}")
    return cache[query]


def main() -> None:
    ref = pd.read_csv(SEEDS / "venue_reference.csv")
    BRONZE.mkdir(parents=True, exist_ok=True)
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}

    # Several schedule labels share one place (e.g. Convention Center Halls 1-3), so we
    # geocode each unique place once.
    rows = []
    for query in ref.geocode_query.unique():
        hit = geocode(query, cache)
        rows.append({
            "geocode_query": query,
            "lat": float(hit["lat"]) if hit else None,
            "lon": float(hit["lon"]) if hit else None,
            "osm_display_name": hit["display_name"] if hit else None,
            "geocode_source": "nominatim" if hit else None,
        })
    CACHE.write_text(json.dumps(cache, indent=1))
    geo = pd.DataFrame(rows)

    # Where the lookup picked the wrong spot, our hand-checked coordinates win.
    overrides = pd.read_csv(SEEDS / "venue_geocode_overrides.csv").assign(
        geocode_source="manual_override")
    geo = geo.set_index("geocode_query")
    geo.update(overrides.set_index("geocode_query"))
    geo = geo.reset_index()

    # Attach the coordinates back to all 49 venue labels.
    venues = ref.merge(geo, on="geocode_query", how="left")
    missing = venues[venues.lat.isna()]
    if len(missing):
        print("NOT FOUND (add these to venue_geocode_overrides.csv):")
        print(missing[["venue_label", "geocode_query"]].to_string(index=False))

    path = BRONZE / "venues.parquet"
    venues.to_parquet(path, index=False)
    venues.to_csv(path.with_suffix(".csv"), index=False)
    print(f"{venues.lat.notna().sum()}/{len(venues)} venue labels have coordinates -> {path}")


if __name__ == "__main__":
    main()
