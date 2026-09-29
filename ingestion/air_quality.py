"""Air quality near venues.

History (no key): EPA AirData pre-generated daily summary files -- daily max
8-hour ozone (parameter 44201) and PM2.5 (88101) at every regulatory monitor.
We keep monitors within MAX_KM of any venue, July-August only.

Current (key): EPA AirNow observations by lat/lon, if AIRNOW_API_KEY is set.

Usage:  uv run python -m ingestion.air_quality [--years 2019 ... 2024]
"""

from __future__ import annotations

import argparse
import zipfile

import numpy as np
import pandas as pd
import requests

from ingestion.common import BRONZE, env, get_json, venues, write_bronze

AIRDATA = "https://aqs.epa.gov/aqsweb/airdata/daily_{param}_{year}.zip"
PARAMS = {"44201": "ozone", "88101": "pm25"}
MAX_KM = 25
AIRNOW = "https://www.airnowapi.org/aq/observation/latLong/current/"


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * np.arcsin(np.sqrt(a))


def airdata_year(param: str, year: int) -> pd.DataFrame:
    cache = BRONZE / "airdata" / f"daily_{param}_{year}.zip"
    cache.parent.mkdir(parents=True, exist_ok=True)
    if not cache.exists():
        r = requests.get(AIRDATA.format(param=param, year=year), timeout=300)
        r.raise_for_status()
        cache.write_bytes(r.content)
    with zipfile.ZipFile(cache) as z, z.open(z.namelist()[0]) as f:
        df = pd.read_csv(f, low_memory=False)
    df["Date Local"] = pd.to_datetime(df["Date Local"])
    return df[df["Date Local"].dt.month.isin([7, 8])]


def nearest_monitors(df: pd.DataFrame, sites: pd.DataFrame) -> pd.DataFrame:
    mons = df[["State Code", "County Code", "Site Num", "Latitude", "Longitude"]].drop_duplicates()
    pairs = sites.merge(mons, how="cross")
    pairs["distance_km"] = haversine_km(pairs.lat, pairs.lon, pairs.Latitude, pairs.Longitude)
    return pairs[pairs.distance_km <= MAX_KM][["venue_id", "State Code", "County Code", "Site Num",
                                                "distance_km"]]


def history(years: list[int]) -> pd.DataFrame:
    sites = venues().drop_duplicates("venue_id")[["venue_id", "lat", "lon"]]
    frames = []
    for param, name in PARAMS.items():
        for y in years:
            df = airdata_year(param, y)
            near = nearest_monitors(df, sites)
            df = df.merge(near, on=["State Code", "County Code", "Site Num"])
            df["pollutant"] = name
            frames.append(df)
            print(f"{name} {y}: {len(df):,} venue-monitor-days")
    out = pd.concat(frames, ignore_index=True)
    out.columns = [c.lower().replace(" ", "_").replace("(", "").replace(")", "") for c in out.columns]
    return out


def airnow_current() -> pd.DataFrame | None:
    key = env("AIRNOW_API_KEY")
    if not key:
        print("AIRNOW_API_KEY not set; skipping current AirNow observations")
        return None
    sites = venues().drop_duplicates("venue_id")
    frames = []
    for s in sites.itertuples():
        obs = get_json(AIRNOW, params={"format": "application/json", "latitude": s.lat,
                                       "longitude": s.lon, "distance": MAX_KM, "API_KEY": key})
        if obs:
            df = pd.DataFrame(obs)
            df["venue_id"] = s.venue_id
            frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, nargs="+", default=list(range(2019, 2025)))
    a = ap.parse_args()
    write_bronze(history(a.years), "aq_daily_history")
    cur = airnow_current()
    if cur is not None:
        write_bronze(cur, "airnow_current")


if __name__ == "__main__":
    main()
