"""Stage 6: daily ozone and PM2.5 at air-quality monitors near each venue (EPA AirData).

Input:  data/bronze/venues.parquet
Output: data/bronze/aq_daily_history.parquet (+ .csv copy)

The EPA publishes one zipped CSV per pollutant per year, covering every regulatory monitor
in the US (~5-10 MB each). No key needed. We download each file once (cached in
data/bronze/airdata/), keep July-August, and keep only monitors within 25 km of a venue.

  ozone (parameter 44201): daily maximum 8-hour average, with its AQI
  PM2.5 (parameter 88101): fine particles, daily average, with its AQI

Usage:  uv run python -m ingestion.air_quality                  (2019-2024)
        uv run python -m ingestion.air_quality --years 2024
"""

import argparse
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import requests

AIRDATA = "https://aqs.epa.gov/aqsweb/airdata/daily_{param}_{year}.zip"
PARAMS = {"44201": "ozone", "88101": "pm25"}
MAX_KM = 25  # a monitor counts as "near" a venue within this distance
BRONZE = Path("data/bronze")
CACHE = BRONZE / "airdata"


def haversine_km(lat1, lon1, lat2, lon2):
    """Distance between two points on Earth, in km (the standard great-circle formula)."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * np.arcsin(np.sqrt(a))


def airdata_year(param: str, year: int) -> pd.DataFrame:
    """One pollutant, one year, every US monitor: download once, then read from the cache."""
    path = CACHE / f"daily_{param}_{year}.zip"
    if not path.exists():
        print(f"  downloading {path.name}")
        r = requests.get(AIRDATA.format(param=param, year=year), timeout=300)
        r.raise_for_status()
        path.write_bytes(r.content)
    with zipfile.ZipFile(path) as z, z.open(z.namelist()[0]) as f:  # the zip holds one CSV
        df = pd.read_csv(f, low_memory=False)
    df["Date Local"] = pd.to_datetime(df["Date Local"])
    return df[df["Date Local"].dt.month.isin([7, 8])]  # Games season only


def nearby_monitors(df: pd.DataFrame, sites: pd.DataFrame) -> pd.DataFrame:
    """Pair every venue with every monitor, measure the distance, keep pairs within MAX_KM."""
    monitors = df[["State Code", "County Code", "Site Num", "Latitude", "Longitude"]].drop_duplicates()
    pairs = sites.merge(monitors, how="cross")  # every venue x every monitor
    pairs["distance_km"] = haversine_km(pairs.lat, pairs.lon, pairs.Latitude, pairs.Longitude)
    near = pairs[pairs.distance_km <= MAX_KM]
    return near[["venue_id", "State Code", "County Code", "Site Num", "distance_km"]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, nargs="+", default=list(range(2019, 2025)))
    a = ap.parse_args()

    CACHE.mkdir(parents=True, exist_ok=True)
    sites = pd.read_parquet(BRONZE / "venues.parquet").drop_duplicates("venue_id")[
        ["venue_id", "lat", "lon"]]

    frames = []
    for param, name in PARAMS.items():
        for year in a.years:
            df = airdata_year(param, year)
            # A monitor (identified by state + county + site number) near two venues
            # appears twice, once per venue.
            df = df.merge(nearby_monitors(df, sites), on=["State Code", "County Code", "Site Num"])
            df["pollutant"] = name
            frames.append(df)
            print(f"{name} {year}: {len(df):,} venue-monitor-days")

    out = pd.concat(frames, ignore_index=True)
    # "Arithmetic Mean" -> "arithmetic_mean": tidy, SQL-friendly column names
    out.columns = [c.lower().replace(" ", "_").replace("(", "").replace(")", "") for c in out.columns]

    path = BRONZE / "aq_daily_history.parquet"
    out.to_parquet(path, index=False)
    out.to_csv(path.with_suffix(".csv"), index=False)
    print(f"{len(out):,} rows -> {path}")


if __name__ == "__main__":
    main()
