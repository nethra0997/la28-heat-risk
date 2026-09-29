"""Forecast WBGT per venue location from the NWS hourly forecast (dbt Python model).

NWS hourly forecasts don't include solar radiation, so we estimate it: Haurwitz
clear-sky irradiance from sun angle, scaled by a cloud factor read from the
forecast wording ("Sunny", "Partly Cloudy", ...). Coarser than the reanalysis
baseline -- good enough for a 7-day heads-up, and labelled as an estimate.
"""

import numpy as np
import pandas as pd

from heatrisk.wbgt import cos_zenith, wbgt, wind_at_2m

CALM_FLOOR_MS = 1.0

# Order matters: first match wins ("Mostly Sunny" before "Sunny").
SKY_FACTORS = [
    ("mostly sunny", 0.85), ("mostly clear", 0.85), ("partly sunny", 0.55), ("partly cloudy", 0.65),
    ("mostly cloudy", 0.4), ("sunny", 1.0), ("clear", 1.0), ("fog", 0.35), ("haze", 0.8),
    ("cloudy", 0.25), ("overcast", 0.25), ("rain", 0.2), ("showers", 0.3), ("thunderstorm", 0.2),
]


def sky_factor(text: str) -> float:
    t = (text or "").lower()
    for key, f in SKY_FACTORS:
        if key in t:
            return f
    return 0.7


def model(dbt, session):
    dbt.config(materialized="table")
    fc = dbt.ref("stg_nws_forecast").df()
    locs = dbt.ref("stg_venues").df().drop_duplicates("loc_id")[["loc_id", "lat", "lon"]]
    fc = fc.merge(locs, on="loc_id")

    t = pd.to_datetime(fc["time_utc"], utc=True) + pd.Timedelta(minutes=30)  # mid-hour
    cza = cos_zenith(t, fc["lat"].to_numpy(), fc["lon"].to_numpy())
    czp = np.maximum(cza, 1e-3)
    clear_sky = np.where(cza > 0, 1098.0 * cza * np.exp(-0.057 / czp), 0.0)  # Haurwitz (1945)
    factor = fc["short_forecast"].map(sky_factor).to_numpy()
    ghi = clear_sky * factor
    # Low-pressure assumption is fine near sea level; forecast has no pressure field.
    # NWS rounds light air to "0 mph" (calm = under ~3 mph). Feeding 0 into the model
    # removes convective cooling and inflates WBGT by several degrees, so floor at 1 m/s.
    wind10 = np.maximum(fc["wind_10m_ms"].fillna(2.0).to_numpy(), CALM_FLOOR_MS)
    res = wbgt(fc["temp_c"], fc["rh_pct"], np.full(len(fc), 1013.0),
               wind_at_2m(wind10), ghi, cza, fdir=None)

    out = fc[["loc_id", "time_utc", "temp_c", "rh_pct", "wind_10m_ms", "short_forecast", "issued_at"]].copy()
    out["ghi_est_wm2"] = ghi
    out["wbgt_sun_c"] = res["wbgt_c"].to_numpy()
    return out
