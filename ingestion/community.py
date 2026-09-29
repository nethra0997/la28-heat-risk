"""Community heat vulnerability around venues: census tracts, CDC/ATSDR SVI, Census ACS.

* Tract shapes: Census cartographic boundary file (500k), California.
* SVI 2022: CDC/ATSDR Social Vulnerability Index, tract level (RPL_THEMES = overall percentile).
* ACS 5-year: share age 65+, households without a vehicle, poverty -- the groups
  public-health heat plans single out. Requires CENSUS_API_KEY (optional enrichment).

Output tables:
  bronze/tracts.parquet              tract geometry (WKT) + centroid
  bronze/svi_tracts.parquet          SVI columns we use
  bronze/acs_tracts.parquet          raw ACS counts
  bronze/venue_tracts.parquet        which tracts fall within each venue buffer

Usage:  uv run python -m ingestion.community
"""

from __future__ import annotations

import io
import zipfile

import geopandas as gpd
import pandas as pd
import requests

from ingestion.common import BRONZE, env, get_json, venues, write_bronze

STATE_FIPS = "06"
TRACTS_URL = "https://www2.census.gov/geo/tiger/GENZ2022/shp/cb_2022_06_tract_500k.zip"
SVI_URL = "https://svi.cdc.gov/Documents/Data/2022/csv/states/California.csv"
ACS_URL = "https://api.census.gov/data/2022/acs/acs5"
BUFFER_M = 3000  # "neighbourhood" around a venue: spectators, workers, residents
SVI_COLS = ["FIPS", "COUNTY", "E_TOTPOP", "RPL_THEME1", "RPL_THEME2", "RPL_THEME3", "RPL_THEME4",
            "RPL_THEMES", "EP_AGE65", "EP_NOVEH", "EP_POV150", "EP_UNINSUR", "EP_LIMENG"]

ACS_VARS = {
    "B01001_001E": "pop_total",
    **{f"B01001_0{i}E": f"m65_{i}" for i in range(20, 26)},
    **{f"B01001_0{i}E": f"f65_{i}" for i in range(44, 50)},
    "B25044_001E": "hh_total", "B25044_003E": "hh_owner_noveh", "B25044_010E": "hh_renter_noveh",
    "B17001_001E": "pov_universe", "B17001_002E": "pov_below",
}


def download(url: str, name: str) -> bytes:
    path = BRONZE / "raw" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        r = requests.get(url, timeout=300, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        path.write_bytes(r.content)
    return path.read_bytes()


def tracts() -> gpd.GeoDataFrame:
    z = zipfile.ZipFile(io.BytesIO(download(TRACTS_URL, "cb_2022_06_tract_500k.zip")))
    shp = next(n for n in z.namelist() if n.endswith(".shp"))
    raw = BRONZE / "raw" / "tracts"
    z.extractall(raw)
    return gpd.read_file(raw / shp)[["GEOID", "COUNTYFP", "ALAND", "geometry"]]


def svi() -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(download(SVI_URL, "svi_2022_california.csv")), dtype={"FIPS": str})
    df = df[SVI_COLS].copy()
    # SVI uses -999 for missing
    num = df.columns.drop(["FIPS", "COUNTY"])
    df[num] = df[num].mask(df[num] == -999)
    return df.rename(columns=str.lower).rename(columns={"fips": "geoid"})


def acs(counties: list[str]) -> pd.DataFrame:
    """ACS counts per tract. The Census API now requires a key; without one we write an
    empty table and the dbt model falls back to SVI's ACS-derived estimates."""
    if not env("CENSUS_API_KEY"):
        print("CENSUS_API_KEY not set; ACS enrichment skipped (SVI estimates used instead)")
        return pd.DataFrame(columns=["geoid", *ACS_VARS.values()]).astype(
            {"geoid": str, **{c: float for c in ACS_VARS.values()}})
    frames = []
    for c in counties:
        params = {"get": ",".join(ACS_VARS), "for": "tract:*", "in": f"state:{STATE_FIPS} county:{c}"}
        params["key"] = env("CENSUS_API_KEY")
        rows = get_json(ACS_URL, params=params)
        frames.append(pd.DataFrame(rows[1:], columns=rows[0]))
    df = pd.concat(frames, ignore_index=True).rename(columns=ACS_VARS)
    df["geoid"] = df.state + df.county + df.tract
    num = list(ACS_VARS.values())
    df[num] = df[num].apply(pd.to_numeric).mask(lambda x: x < 0)
    return df[["geoid", *num]]


def main() -> None:
    v = venues().drop_duplicates("venue_id")
    v = v[v.region != "remote"]  # out-of-state / city-level points
    venue_pts = gpd.GeoDataFrame(v[["venue_id"]], geometry=gpd.points_from_xy(v.lon, v.lat), crs=4326)

    tr = tracts()
    # California Albers (EPSG:3310) for metre-accurate buffers and areas
    tr_m, pts_m = tr.to_crs(3310), venue_pts.to_crs(3310)
    buffers = pts_m.assign(geometry=pts_m.buffer(BUFFER_M))
    hits = gpd.overlay(tr_m, buffers, how="intersection", keep_geom_type=True)
    hits["overlap_m2"] = hits.area
    tr_area = tr_m.set_index("GEOID").area
    hits["overlap_share_of_tract"] = hits.overlap_m2 / hits.GEOID.map(tr_area)
    venue_tracts = hits[["venue_id", "GEOID", "overlap_m2", "overlap_share_of_tract"]].rename(
        columns={"GEOID": "geoid"})

    counties = sorted(tr[tr.GEOID.isin(venue_tracts.geoid)].COUNTYFP.unique())
    cent = tr_m.centroid.to_crs(4326)
    tr_out = pd.DataFrame({"geoid": tr.GEOID, "countyfp": tr.COUNTYFP, "aland_m2": tr.ALAND,
                           "centroid_lat": cent.y, "centroid_lon": cent.x,
                           "geometry_wkt": tr.geometry.to_wkt()})
    tr_out = tr_out[tr_out.countyfp.isin(counties)]

    write_bronze(tr_out, "tracts")
    write_bronze(venue_tracts, "venue_tracts")
    write_bronze(svi(), "svi_tracts")
    write_bronze(acs(counties), "acs_tracts")
    print(f"{venue_tracts.venue_id.nunique()} venues, {venue_tracts.geoid.nunique()} tracts, "
          f"counties {counties}")


if __name__ == "__main__":
    main()
