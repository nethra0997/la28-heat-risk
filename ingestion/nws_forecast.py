"""Stage 6: 7-day hourly forecast per venue from the US National Weather Service.

Input:  data/bronze/venues.parquet
Output: data/bronze/nws_forecast_hourly.parquet (+ .csv copy)

api.weather.gov is free and needs no key, but asks every caller to identify itself
(User-Agent). Getting a forecast takes two calls per place:
  1. /points/{lat},{lon}   -> "this point is in forecast grid LOX 154,44"
  2. that grid's /forecast/hourly URL -> one row per hour for the next ~7 days

Usage:  uv run python -m ingestion.nws_forecast
"""

import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import requests

BASE = "https://api.weather.gov"
USER_AGENT = "la28-heat-risk (learning project; github.com/nethra0997/la28-heat-risk)"
BRONZE = Path("data/bronze")


def get_json(url: str) -> dict:
    """GET with up to 3 tries: NWS grid endpoints fail now and then with a 500 error."""
    for attempt in range(3):
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
        if r.status_code < 500:
            break
        time.sleep(2 * (attempt + 1))
    r.raise_for_status()
    return r.json()


def forecast_hourly(lat: float, lon: float) -> pd.DataFrame:
    point = get_json(f"{BASE}/points/{lat:.4f},{lon:.4f}")["properties"]  # call 1: which grid?
    periods = get_json(point["forecastHourly"])["properties"]["periods"]    # call 2: the forecast
    df = pd.json_normalize(periods)  # flattens nested JSON, e.g. dewpoint.value -> a column
    df["grid_id"], df["grid_x"], df["grid_y"] = point["gridId"], point["gridX"], point["gridY"]
    return df


def main() -> None:
    v = pd.read_parquet(BRONZE / "venues.parquet")
    v["loc_id"] = v.lat.round(3).astype(str) + "_" + v.lon.round(3).astype(str)
    locs = v.drop_duplicates("loc_id")

    frames = []
    for loc in locs.itertuples():
        try:
            df = forecast_hourly(loc.lat, loc.lon)
        except requests.RequestException as e:  # one bad place shouldn't stop the others
            print(f"  skipped {loc.loc_id}: {e}")
            continue
        df["loc_id"] = loc.loc_id
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)

    # Keep the useful fields and give them tidy names.
    keep = {
        "startTime": "start_time", "endTime": "end_time", "isDaytime": "is_daytime",
        "temperature": "temperature", "temperatureUnit": "temperature_unit",
        "windSpeed": "wind_speed_text", "windDirection": "wind_direction",
        "shortForecast": "short_forecast",
        "probabilityOfPrecipitation.value": "precip_probability_pct",
        "dewpoint.value": "dewpoint_c", "relativeHumidity.value": "relative_humidity_pct",
    }
    df = df[[c for c in keep if c in df] + ["loc_id", "grid_id", "grid_x", "grid_y"]].rename(columns=keep)
    df["issued_at"] = datetime.now(UTC)  # when we pulled it: forecasts go stale

    path = BRONZE / "nws_forecast_hourly.parquet"
    df.to_parquet(path, index=False)
    df.to_csv(path.with_suffix(".csv"), index=False)
    print(f"{len(df):,} forecast hours for {df.loc_id.nunique()} places -> {path}")


if __name__ == "__main__":
    main()
