"""Stage 6: how vulnerable to heat are the neighbourhoods around each venue?

Input:  data/bronze/venues.parquet
Output: data/bronze/tracts.parquet        census tract shapes (in the counties near venues)
        data/bronze/svi_tracts.parquet    CDC vulnerability scores per tract (+ .csv)
        data/bronze/venue_tracts.parquet  which tracts fall within 3 km of each venue (+ .csv)

Census tracts are small neighbourhoods (~4,000 people each) with fixed boundaries and an ID
(GEOID). Two downloads, no key:
  * Census Bureau: the boundary shape of every California tract (a zipped shapefile)
  * CDC/ATSDR Social Vulnerability Index 2022: one row per California tract

The spatial join: draw a 3 km circle around each venue and find the tracts it overlaps.
California venues only; this data is for one state.

Usage:  uv run python -m ingestion.community
"""

import io
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests

TRACTS_URL = "https://www2.census.gov/geo/tiger/GENZ2022/shp/cb_2022_06_tract_500k.zip"
SVI_URL = "https://svi.cdc.gov/Documents/Data/2022/csv/states/California.csv"
BUFFER_M = 3000  # the "neighbourhood" around a venue: spectators, workers, residents

# SVI columns we keep. RPL_* are percentiles (0-1, higher = more vulnerable);
# EP_* are estimated percentages of the tract's population.
SVI_COLS = {
    "FIPS": "geoid", "COUNTY": "county", "E_TOTPOP": "pop_total",
    "RPL_THEMES": "svi_overall_pctile",          # overall vulnerability
    "RPL_THEME1": "svi_socioeconomic_pctile",    # poverty, unemployment, housing cost...
    "RPL_THEME2": "svi_household_pctile",        # age, disability, single parents...
    "RPL_THEME3": "svi_minority_language_pctile",
    "RPL_THEME4": "svi_housing_transport_pctile",
    "EP_AGE65": "pct_age_65_plus",               # older people: higher heat-illness risk
    "EP_NOVEH": "pct_households_no_vehicle",     # can't easily get to a cool place
    "EP_POV150": "pct_below_150pct_poverty",
}

BRONZE = Path("data/bronze")
RAW = BRONZE / "raw"


def download(url: str, name: str) -> bytes:
    """Download once into data/bronze/raw/, then reuse the saved copy."""
    path = RAW / name
    if not path.exists():
        print(f"  downloading {name}")
        r = requests.get(url, timeout=300, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        path.write_bytes(r.content)
    return path.read_bytes()


def tracts() -> gpd.GeoDataFrame:
    """Every California tract with its boundary shape."""
    z = zipfile.ZipFile(io.BytesIO(download(TRACTS_URL, "cb_2022_06_tract_500k.zip")))
    z.extractall(RAW / "tracts")  # a "shapefile" is several files (.shp, .dbf, ...) that go together
    shp = next(n for n in z.namelist() if n.endswith(".shp"))
    return gpd.read_file(RAW / "tracts" / shp)[["GEOID", "COUNTYFP", "geometry"]]


def svi() -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(download(SVI_URL, "svi_2022_california.csv")), dtype={"FIPS": str})
    df = df[list(SVI_COLS)].rename(columns=SVI_COLS)
    numeric = df.columns.drop(["geoid", "county"])
    df[numeric] = df[numeric].mask(df[numeric] == -999)  # SVI writes -999 for "no data"
    return df


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    v = pd.read_parquet(BRONZE / "venues.parquet").drop_duplicates("venue_id")
    v = v[v.region != "remote"]  # out-of-state venues: no California tracts there
    points = gpd.GeoDataFrame(v[["venue_id"]], geometry=gpd.points_from_xy(v.lon, v.lat), crs=4326)

    tr = tracts()

    # Latitude/longitude are angles, not distances. To draw a 3 km circle and measure areas,
    # convert both layers to a map projection in metres (EPSG:3310, California Albers).
    tr_m, points_m = tr.to_crs(3310), points.to_crs(3310)
    circles = points_m.assign(geometry=points_m.buffer(BUFFER_M))

    # The spatial join: the pieces of each tract that fall inside each venue's circle.
    hits = gpd.overlay(tr_m, circles, how="intersection", keep_geom_type=True)
    hits["overlap_m2"] = hits.area
    tract_area = tr_m.set_index("GEOID").area
    hits["overlap_share_of_tract"] = hits.overlap_m2 / hits.GEOID.map(tract_area)
    venue_tracts = hits[["venue_id", "GEOID", "overlap_m2", "overlap_share_of_tract"]].rename(
        columns={"GEOID": "geoid"})

    # Keep tract shapes only for counties that touch a venue (for mapping later).
    counties = sorted(tr[tr.GEOID.isin(venue_tracts.geoid)].COUNTYFP.unique())
    centroids = tr_m.centroid.to_crs(4326)
    tracts_out = pd.DataFrame({
        "geoid": tr.GEOID, "countyfp": tr.COUNTYFP,
        "centroid_lat": centroids.y, "centroid_lon": centroids.x,
        "geometry_wkt": tr.geometry.to_wkt(),  # the shape as text, so Parquet can store it
    })
    tracts_out = tracts_out[tracts_out.countyfp.isin(counties)]

    svi_out = svi()
    tracts_out.to_parquet(BRONZE / "tracts.parquet", index=False)
    for name, df in [("svi_tracts", svi_out), ("venue_tracts", venue_tracts)]:
        df.to_parquet(BRONZE / f"{name}.parquet", index=False)
        df.to_csv(BRONZE / f"{name}.csv", index=False)

    print(f"{venue_tracts.venue_id.nunique()} venues, {venue_tracts.geoid.nunique()} tracts "
          f"within {BUFFER_M // 1000} km, in counties {counties}; {len(svi_out):,} SVI tracts")


if __name__ == "__main__":
    main()
