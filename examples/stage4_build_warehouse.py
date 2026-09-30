"""Stage 4: build a small DuckDB warehouse from the bronze files, by hand.

Creates data/warehouse.duckdb with three tables:
  venues         the 49 venue labels, with loc_id so they can be joined to weather
  weather_hourly the 485,760 bronze weather rows
  weather_wbgt   one row per place per hour, with WBGT in sun and shade (computed in Python)

This is deliberately a plain script. In Stage 5, dbt replaces it with an organised,
tested chain of models, and this file becomes unnecessary.

Usage:  uv run python -m examples.stage4_build_warehouse
"""

import time

import duckdb
import numpy as np

from heatrisk.wbgt import cos_zenith, wbgt, wind_at_2m

WAREHOUSE = "data/warehouse.duckdb"

con = duckdb.connect(WAREHOUSE)  # opens the file, or creates it if it doesn't exist

# 1. Copy the bronze Parquet files into database tables. DuckDB reads Parquet directly.
con.sql("""
    create or replace table venues as
    select *,
           -- same place ID the weather script built in Python, so the two tables can be joined
           round(lat, 3)::varchar || '_' || round(lon, 3)::varchar as loc_id
    from read_parquet('data/bronze/venues.parquet')
""")
con.sql("""
    create or replace table weather_hourly as
    select w.*, l.lat, l.lon
    from read_parquet('data/bronze/weather_hourly_history.parquet') w
    join read_parquet('data/bronze/weather_locations.parquet') l using (loc_id)
""")
print("loaded venues:", con.sql("select count(*) from venues").fetchone()[0], "rows")
print("loaded weather_hourly:", con.sql("select count(*) from weather_hourly").fetchone()[0], "rows")

# 2. SQL can't run the physics, so pull the weather into Python, compute WBGT, write it back.
t0 = time.time()
df = con.sql("select * from weather_hourly").df()

# Sunlight columns are averages over the hour ending at time_utc -> put the sun at mid-hour.
cza = cos_zenith(df.time_utc - np.timedelta64(30, "m"), df.lat.to_numpy(), df.lon.to_numpy())
with np.errstate(divide="ignore", invalid="ignore"):
    fdir = np.where(df.shortwave_radiation > 0, df.direct_radiation / df.shortwave_radiation, 0.0)
u2 = wind_at_2m(df.wind_speed_10m.to_numpy())
n = len(df)

sun = wbgt(df.temperature_2m, df.relative_humidity_2m, df.surface_pressure, u2,
           df.shortwave_radiation, cza, fdir)
shade = wbgt(df.temperature_2m, df.relative_humidity_2m, df.surface_pressure, u2,
             np.zeros(n), np.zeros(n))

out = df[["loc_id", "time_utc", "temperature_2m", "relative_humidity_2m",
          "wind_speed_10m", "shortwave_radiation"]].copy()
out["globe_temp_c"] = sun.globe_temp_c.to_numpy()
out["natural_wet_bulb_c"] = sun.natural_wet_bulb_c.to_numpy()
out["wbgt_sun_c"] = sun.wbgt_c.to_numpy()
out["wbgt_shade_c"] = shade.wbgt_c.to_numpy()

# DuckDB can read a pandas table that exists in Python by its variable name (`out`).
con.sql("""
    create or replace table weather_wbgt as
    select *, timezone('America/Los_Angeles', time_utc) as time_local
    from out
""")
print(f"computed weather_wbgt: {len(out):,} rows in {time.time() - t0:.1f}s")

con.close()
print(f"warehouse ready -> {WAREHOUSE}")
