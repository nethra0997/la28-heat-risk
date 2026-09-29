"""Hourly historical weather per venue from the Open-Meteo archive API (ERA5-based, no key).

LA28 runs July 10-30, 2028. We pull the same calendar window (July 1 - Aug 15) for
a multi-year baseline so every session gets a climatological WBGT distribution.

Usage:  uv run python -m ingestion.open_meteo [--start-year 2015 --end-year 2025]
"""

from __future__ import annotations

import argparse
import time

import pandas as pd
import requests

from ingestion.common import BRONZE, get_json, venues, write_bronze

CACHE = BRONZE / "raw" / "open_meteo"

URL = "https://archive-api.open-meteo.com/v1/archive"
HOURLY = [
    "temperature_2m", "relative_humidity_2m", "dew_point_2m", "surface_pressure",
    "wind_speed_10m", "cloud_cover", "shortwave_radiation", "direct_radiation",
    "diffuse_radiation", "direct_normal_irradiance",
]
BATCH = 10  # Open-Meteo accepts comma-separated coordinate lists


def locations() -> pd.DataFrame:
    """Unique venue points (several schedule labels share a site)."""
    v = venues()
    v["loc_id"] = v.lat.round(3).astype(str) + "_" + v.lon.round(3).astype(str)
    return v.drop_duplicates("loc_id")[["loc_id", "lat", "lon"]].reset_index(drop=True)


def fetch(locs: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    params = {
        "latitude": ",".join(f"{x:.4f}" for x in locs.lat),
        "longitude": ",".join(f"{x:.4f}" for x in locs.lon),
        "start_date": start, "end_date": end,
        "hourly": ",".join(HOURLY),
        "wind_speed_unit": "ms",
        "timezone": "GMT",
    }
    for attempt in range(6):
        try:
            payload = get_json(URL, params=params)
            break
        except requests.HTTPError as e:
            if e.response is None or e.response.status_code != 429:
                raise
            wait = 65 * (attempt + 1)  # free tier limits are per minute / hour
            print(f"  rate limited; sleeping {wait}s")
            time.sleep(wait)
    else:
        raise RuntimeError("Open-Meteo rate limit did not clear")
    if isinstance(payload, dict):
        payload = [payload]
    frames = []
    for loc, p in zip(locs.itertuples(), payload):
        df = pd.DataFrame(p["hourly"])
        df["loc_id"] = loc.loc_id
        df["grid_lat"], df["grid_lon"], df["grid_elevation_m"] = p["latitude"], p["longitude"], p["elevation"]
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-year", type=int, default=2015)
    ap.add_argument("--end-year", type=int, default=2025)
    a = ap.parse_args()

    locs = locations()
    frames = []
    CACHE.mkdir(parents=True, exist_ok=True)
    for year in range(a.start_year, a.end_year + 1):
        for i in range(0, len(locs), BATCH):
            chunk = locs.iloc[i:i + BATCH]
            path = CACHE / f"{year}_{'-'.join(chunk.loc_id)}.parquet"
            if not path.exists():  # resumable: finished chunks are cached on disk
                fetch(chunk, f"{year}-07-01", f"{year}-08-15").to_parquet(path, index=False)
                time.sleep(3)
            frames.append(pd.read_parquet(path))
        print(f"{year}: {len(locs)} locations")
    df = pd.concat(frames, ignore_index=True).rename(columns={"time": "time_utc"})
    df["time_utc"] = pd.to_datetime(df.time_utc, utc=True)
    write_bronze(df, "weather_hourly_history")
    write_bronze(locs, "weather_locations")
    print(f"{len(df):,} hourly rows")


if __name__ == "__main__":
    main()
