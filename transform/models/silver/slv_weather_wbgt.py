"""Hourly WBGT for every venue location and baseline hour (dbt Python model, runs in DuckDB's process).

Physics lives in heatrisk.wbgt (unit-tested); this model only wires columns in.
"""

import numpy as np

from heatrisk.wbgt import cos_zenith, wbgt, wind_at_2m


def model(dbt, session):
    dbt.config(materialized="table")
    df = dbt.ref("stg_weather_hourly").df()

    # Radiation is the mean over the hour ending at time_utc -> evaluate the sun at mid-hour.
    mid_hour = df["time_utc"] - np.timedelta64(30, "m")
    cza = cos_zenith(mid_hour, df["lat"].to_numpy(), df["lon"].to_numpy())
    with np.errstate(divide="ignore", invalid="ignore"):
        fdir = np.where(df["ghi_wm2"] > 0, df["direct_wm2"] / df["ghi_wm2"], 0.0)
    u2 = wind_at_2m(df["wind_10m_ms"].to_numpy())

    sun = wbgt(df["temp_c"], df["rh_pct"], df["pressure_hpa"], u2, df["ghi_wm2"], cza, fdir)
    n = len(df)
    shade = wbgt(df["temp_c"], df["rh_pct"], df["pressure_hpa"], u2, np.zeros(n), np.zeros(n))

    out = df[["loc_id", "time_utc", "time_local", "year_local", "temp_c", "rh_pct",
              "wind_10m_ms", "ghi_wm2", "precip_mm"]].copy()
    out["cos_zenith"] = cza
    out["wind_2m_ms"] = u2
    out["globe_temp_c"] = sun["globe_temp_c"].to_numpy()
    out["natural_wet_bulb_c"] = sun["natural_wet_bulb_c"].to_numpy()
    out["wbgt_sun_c"] = sun["wbgt_c"].to_numpy()
    out["wbgt_shade_c"] = shade["wbgt_c"].to_numpy()
    return out
