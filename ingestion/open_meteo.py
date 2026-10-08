"""Stage 2B: hourly weather for every venue, July 1 - Aug 15, for 11 summers (2015-2025).

Input:  data/bronze/venues.parquet (from ingestion.venues)
Output: data/bronze/weather_hourly_history.parquet  one row per place per hour
        data/bronze/weather_locations.parquet       the unique places we pulled

Open-Meteo serves ERA5 reanalysis (past weather, reconstructed hourly on a ~25 km grid).
It is free and needs no key, but limits how much you can ask for per minute.

Usage:  uv run python -m ingestion.open_meteo                       (all 11 summers)
        uv run python -m ingestion.open_meteo --start-year 2025     (just one summer)
"""

import argparse
import time
from pathlib import Path

import pandas as pd
import requests

URL = "https://archive-api.open-meteo.com/v1/archive"

# Everything the heat-stress (WBGT) calculation in Stage 3 needs, one value per hour.
HOURLY = [
    "temperature_2m",            # air temperature, °C
    "relative_humidity_2m",      # %
    "dew_point_2m",              # °C, another way of stating humidity
    "surface_pressure",          # hPa, air pressure (affects evaporation)
    "wind_speed_10m",            # m/s
    "cloud_cover",               # %
    "shortwave_radiation",       # W/m², all sunlight on flat ground...
    "direct_radiation",          # ...split into the straight-from-the-sun part
    "diffuse_radiation",         # ...and the scattered-by-the-sky part
    "direct_normal_irradiance",  # W/m², direct sun on a surface facing the sun
    "precipitation",             # mm of rain in the preceding hour (for the fan guide)
]

BRONZE = Path("data/bronze")
CACHE = BRONZE / "raw" / "open_meteo"  # one small file per API call, so reruns skip finished work
BATCH = 10  # Open-Meteo accepts up to many places per call; 10 keeps each answer modest


def locations() -> pd.DataFrame:
    """The unique places to pull. Several venue labels share a site (e.g. Convention Center
    Halls 1-3), and the weather there is identical, so each site is pulled once."""
    v = pd.read_parquet(BRONZE / "venues.parquet")
    v["loc_id"] = v.lat.round(3).astype(str) + "_" + v.lon.round(3).astype(str)
    return v.drop_duplicates("loc_id")[["loc_id", "lat", "lon"]].reset_index(drop=True)


def fetch(locs: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    """One API call for up to BATCH places. Returns one table with a row per place per hour."""
    params = {
        # Several places in one call: comma-separated lists, in matching order.
        "latitude": ",".join(f"{x:.4f}" for x in locs.lat),
        "longitude": ",".join(f"{x:.4f}" for x in locs.lon),
        "start_date": start,
        "end_date": end,
        "hourly": ",".join(HOURLY),
        "wind_speed_unit": "ms",
        "timezone": "GMT",
    }
    for attempt in range(6):
        r = requests.get(URL, params=params, timeout=120)
        if r.status_code != 429:  # 429 = "Too Many Requests": we hit the rate limit
            break
        wait = 65 * (attempt + 1)  # limits reset per minute, so wait a minute or more
        print(f"  rate limited; waiting {wait}s")
        time.sleep(wait)
    r.raise_for_status()
    payload = r.json()
    if isinstance(payload, dict):  # one place -> one answer; several places -> a list
        payload = [payload]

    frames = []
    for loc, p in zip(locs.itertuples(), payload):  # answers come back in the order we asked
        df = pd.DataFrame(p["hourly"])
        df["loc_id"] = loc.loc_id
        df["grid_lat"], df["grid_lon"] = p["latitude"], p["longitude"]
        df["grid_elevation_m"] = p["elevation"]
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-year", type=int, default=2015)
    ap.add_argument("--end-year", type=int, default=2025)
    a = ap.parse_args()

    locs = locations()
    print(f"{len(locs)} unique places, summers {a.start_year}-{a.end_year}")
    CACHE.mkdir(parents=True, exist_ok=True)

    frames = []
    for year in range(a.start_year, a.end_year + 1):
        for i in range(0, len(locs), BATCH):
            chunk = locs.iloc[i:i + BATCH]
            path = CACHE / f"{year}_batch{i // BATCH}.parquet"
            if path.exists():
                print(f"  {year} batch {i // BATCH}: cached")
            else:
                print(f"  {year} batch {i // BATCH}: downloading {len(chunk)} places")
                fetch(chunk, f"{year}-07-01", f"{year}-08-15").to_parquet(path, index=False)
                time.sleep(3)  # pace ourselves to stay under the per-minute limit
            frames.append(pd.read_parquet(path))

    df = pd.concat(frames, ignore_index=True).rename(columns={"time": "time_utc"})
    df["time_utc"] = pd.to_datetime(df.time_utc, utc=True)

    df.to_parquet(BRONZE / "weather_hourly_history.parquet", index=False)
    locs.to_parquet(BRONZE / "weather_locations.parquet", index=False)
    # The full table is too big to browse as CSV; save the first 1,000 rows to look at.
    df.head(1000).to_csv(BRONZE / "weather_hourly_history_sample.csv", index=False)
    print(f"{len(df):,} hourly rows -> {BRONZE / 'weather_hourly_history.parquet'}")


if __name__ == "__main__":
    main()
