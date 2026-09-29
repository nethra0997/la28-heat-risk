"""7-day hourly forecast per venue from the National Weather Service (api.weather.gov, no key).

Two calls per location: /points/{lat},{lon} resolves the forecast grid, then
/gridpoints/.../forecast/hourly returns hourly periods. NWS asks callers to
send an identifying User-Agent (set in ingestion.common).

Usage:  uv run python -m ingestion.nws_forecast
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from ingestion.common import get_json, venues, write_bronze

BASE = "https://api.weather.gov"


def forecast_hourly(lat: float, lon: float) -> pd.DataFrame:
    pt = get_json(f"{BASE}/points/{lat:.4f},{lon:.4f}")["properties"]
    periods = get_json(pt["forecastHourly"])["properties"]["periods"]
    df = pd.json_normalize(periods)
    df["grid_id"], df["grid_x"], df["grid_y"] = pt["gridId"], pt["gridX"], pt["gridY"]
    return df


def main() -> None:
    v = venues()
    v["loc_id"] = v.lat.round(3).astype(str) + "_" + v.lon.round(3).astype(str)
    locs = v.drop_duplicates("loc_id")
    frames = []
    for loc in locs.itertuples():
        try:
            df = forecast_hourly(loc.lat, loc.lon)
        except Exception as e:  # noqa: BLE001 -- NWS grid endpoints 500 intermittently
            print(f"  {loc.loc_id}: {e}")
            continue
        df["loc_id"] = loc.loc_id
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    keep = {
        "startTime": "start_time", "endTime": "end_time", "isDaytime": "is_daytime",
        "temperature": "temperature", "temperatureUnit": "temperature_unit",
        "windSpeed": "wind_speed_text", "windDirection": "wind_direction",
        "shortForecast": "short_forecast",
        "probabilityOfPrecipitation.value": "precip_probability_pct",
        "dewpoint.value": "dewpoint_c", "relativeHumidity.value": "relative_humidity_pct",
    }
    df = df[[c for c in keep if c in df] + ["loc_id", "grid_id", "grid_x", "grid_y"]].rename(columns=keep)
    df["issued_at"] = datetime.now(UTC)
    write_bronze(df, "nws_forecast_hourly")
    print(f"{len(df):,} forecast hours for {df.loc_id.nunique()} locations")


if __name__ == "__main__":
    main()
