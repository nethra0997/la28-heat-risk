"""Export gold tables from DuckDB to data/gold/ as CSV (Tableau Public) and Parquet (app).

Tableau Public can't connect to DuckDB, so the dashboard reads these flat extracts.

Usage:  uv run python -m heatrisk.export
"""

from __future__ import annotations

import duckdb

from ingestion.common import DATA, WAREHOUSE

GOLD_DIR = DATA / "gold"
TABLES = ["gold_session_risk", "gold_venue_summary", "gold_session_heat", "gold_venue_forecast"]


def main() -> None:
    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    existing = {r[0] for r in con.sql(
        "select table_name from information_schema.tables where table_schema = 'gold'").fetchall()}
    for t in TABLES:
        if t not in existing:
            print(f"skip {t} (not built)")
            continue
        rel = con.sql(f"select * from gold.{t}")
        rel.write_parquet(str(GOLD_DIR / f"{t}.parquet"))
        rel.write_csv(str(GOLD_DIR / f"{t}.csv"))
        print(f"{t}: {rel.count('*').fetchone()[0]:,} rows")

    # Hour-by-hour WBGT profile per venue for late July: the Tableau "heat clock".
    con.sql("""
        select v.venue_id, v.venue_name, v.exposure,
               hour(w.time_local) as hour_local,
               median(w.wbgt_sun_c) as wbgt_sun_median_c,
               quantile_cont(w.wbgt_sun_c, 0.9) as wbgt_sun_p90_c,
               median(w.temp_c) as temp_median_c
        from silver.slv_weather_wbgt w
        join (select distinct venue_id, venue_name, exposure, loc_id from staging.stg_venues) v
          using (loc_id)
        where month(w.time_local) = 7 and day(w.time_local) between 10 and 30
        group by all
        order by venue_id, hour_local
    """).write_csv(str(GOLD_DIR / "venue_hourly_profile.csv"))
    print("venue_hourly_profile.csv written")


if __name__ == "__main__":
    main()
