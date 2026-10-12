"""Export the gold tables from the warehouse to data/gold/ as CSV files for Tableau.

Tableau Public can't connect to a DuckDB file, so the dashboard reads these flat files.
Rows are sorted and decimals rounded, so a file only changes when its data does.
Run after `dbt build`.

Usage:  uv run python -m heatrisk.export
"""

from pathlib import Path

import duckdb
import pandas as pd

WAREHOUSE = Path("data/warehouse.duckdb")
GOLD_DIR = Path("data/gold")
TABLES = ["gold_session_risk", "gold_session_conditions", "gold_venue_conditions",
          "gold_venue_summary", "gold_session_heat", "gold_venue_forecast"]


def write_csv(df: pd.DataFrame, name: str) -> None:
    """Stable output: rows sorted by every column, floats rounded to 4 decimals."""
    floats = df.select_dtypes("float").columns
    df[floats] = df[floats].round(4)
    df.sort_values(list(df.columns), ignore_index=True).to_csv(GOLD_DIR / name, index=False)


def main() -> None:
    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    built = {r[0] for r in con.sql(
        "select table_name from information_schema.tables where table_schema = 'gold'").fetchall()}

    for t in TABLES:
        if t not in built:
            print(f"skip {t} (not built; run dbt build first)")
            continue
        df = con.sql(f"select * from gold.{t}").df()
        write_csv(df, f"{t}.csv")
        print(f"{t}: {len(df):,} rows")

    # Hour-by-hour WBGT per venue for the Games window (July 10-30): which hours of the
    # day are hottest at each venue.
    profile = con.sql("""
        select v.venue_id, v.venue_name, v.exposure,
               hour(w.time_local)               as hour_local,
               median(w.wbgt_sun_c)             as wbgt_sun_median_c,
               quantile_cont(w.wbgt_sun_c, 0.9) as wbgt_sun_p90_c,
               median(w.temp_c)                 as temp_median_c
        from silver.slv_weather_wbgt w
        join (select distinct venue_id, venue_name, exposure, loc_id from staging.stg_venues) v
          using (loc_id)
        where month(w.time_local) = 7 and day(w.time_local) between 10 and 30
        group by all
    """).df()
    write_csv(profile, "venue_hourly_profile.csv")
    print("venue_hourly_profile.csv written")


if __name__ == "__main__":
    main()
