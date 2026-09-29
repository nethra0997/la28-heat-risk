"""Stage 1: pull one week of hourly weather for one venue from the Open-Meteo archive API.

Open-Meteo serves ERA5 reanalysis: a global, gap-free reconstruction of past weather on a
~25 km grid. It is free and needs no API key.

Usage:  uv run python -m ingestion.open_meteo
"""

from pathlib import Path

import pandas as pd
import requests

URL = "https://archive-api.open-meteo.com/v1/archive"

# LA Memorial Coliseum: outdoor, hosts athletics in 2028.
VENUE = {"name": "LA Memorial Coliseum", "lat": 34.0139, "lon": -118.2878}

# The same calendar week as the 2028 Games, one summer back.
START, END = "2024-07-24", "2024-07-30"

# What we ask for, one value per hour. These are the inputs WBGT needs later.
HOURLY = ["temperature_2m", "relative_humidity_2m", "wind_speed_10m", "shortwave_radiation"]

BRONZE = Path("data/bronze")


def fetch() -> dict:
    """Call the API and return the parsed JSON response."""
    params = {
        "latitude": VENUE["lat"],
        "longitude": VENUE["lon"],
        "start_date": START,
        "end_date": END,
        "hourly": ",".join(HOURLY),
        "wind_speed_unit": "ms",  # metres per second, what the physics wants
        "timezone": "GMT",        # store UTC; convert to local time only for display
    }
    r = requests.get(URL, params=params, timeout=60)
    r.raise_for_status()  # turn an HTTP error (404, 429, 500...) into a Python exception
    return r.json()


def to_table(payload: dict) -> pd.DataFrame:
    """The API returns one list per variable; pandas turns those lists into columns."""
    df = pd.DataFrame(payload["hourly"])
    df = df.rename(columns={"time": "time_utc"})
    df["time_utc"] = pd.to_datetime(df.time_utc, utc=True)
    df["venue"] = VENUE["name"]
    # The API snaps our point to the nearest grid cell; keep where the data really comes from.
    df["grid_lat"], df["grid_lon"] = payload["latitude"], payload["longitude"]
    return df


def main() -> None:
    payload = fetch()
    df = to_table(payload)

    BRONZE.mkdir(parents=True, exist_ok=True)
    path = BRONZE / "weather_one_week.parquet"
    df.to_parquet(path, index=False)
    # Parquet is binary (unreadable in a text editor); a CSV copy is for looking at the data.
    df.to_csv(path.with_suffix(".csv"), index=False)

    print(df.head(10).to_string())
    print(f"\n{len(df)} rows -> {path} (+ .csv copy)")


if __name__ == "__main__":
    main()
