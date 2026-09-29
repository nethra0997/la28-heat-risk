"""Summer land surface temperature (LST) around each venue from Landsat 8/9.

Source: Microsoft Planetary Computer STAC, collection `landsat-c2-l2`
(Collection 2 Level-2 surface temperature, band `lwir11`, 30 m).
No account needed: `planetary_computer.sign` adds a short-lived SAS token.

For every clear-sky summer scene we read a small window around each venue and
record the mean *land* LST (water masked via QA bit 7) inside a 500 m and a
2 km radius, plus the median land LST of a 10 km box as a local baseline. `lst_anomaly = LST(500 m) - baseline` shows
whether a venue sits in a local heat island (asphalt, few trees) or a cool spot
(coast, parkland).

Usage:  uv run python -m ingestion.landsat_lst [--years 2021 2022 2023 2024 2025]
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import planetary_computer
import rasterio
from pyproj import Transformer
from pystac_client import Client
from rasterio.windows import from_bounds
from shapely.geometry import Point, shape

from ingestion.common import venues, write_bronze

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
# Collection 2 Level-2 ST scaling: Kelvin = DN * 0.00341802 + 149.0
SCALE, OFFSET = 0.00341802, 149.0
QA_CLEAR_MASK = 0b0000000000011111  # fill, dilated cloud, cirrus, cloud, cloud shadow bits (0-4)
QA_WATER = 1 << 7  # water pixels are excluded: the ocean would dominate coastal baselines
RADII_M = (500, 2000)
BASELINE_HALF_M = 5000
MAX_CLOUD = 20
WORKERS = 8  # I/O bound: parallel HTTP range reads


def search(sites: pd.DataFrame, years: list[int]):
    """One STAC search over the bounding box of all venues, per summer."""
    catalog = Client.open(STAC, modifier=planetary_computer.sign_inplace)
    bbox = [sites.lon.min() - 0.05, sites.lat.min() - 0.05, sites.lon.max() + 0.05, sites.lat.max() + 0.05]
    items = []
    for y in years:
        items += catalog.search(
            collections=["landsat-c2-l2"],
            bbox=bbox,
            datetime=f"{y}-06-15/{y}-09-15",
            filter_lang="cql2-json",
            filter={"op": "and", "args": [
                {"op": "<", "args": [{"property": "eo:cloud_cover"}, MAX_CLOUD]},
                {"op": "in", "args": [{"property": "platform"}, ["landsat-8", "landsat-9"]]},
            ]},
        ).item_collection()
    return items


def window(src, lat: float, lon: float, half: float):
    x, y = Transformer.from_crs(4326, src.crs, always_xy=True).transform(lon, lat)
    win = from_bounds(x - half, y - half, x + half, y + half, src.transform)
    return src.read(1, window=win, boundless=True, fill_value=0)


def stats(lst: np.ndarray, qa: np.ndarray, res: float) -> dict | None:
    clear = (lst > 0) & ((qa & QA_CLEAR_MASK) == 0)
    if clear.mean() < 0.5:  # mostly cloud / outside the scene
        return None
    valid = clear & ((qa & QA_WATER) == 0)
    lst_c = np.where(valid, lst * SCALE + OFFSET - 273.15, np.nan)
    ny, nx = lst_c.shape
    yy, xx = np.mgrid[0:ny, 0:nx]
    dist = np.hypot((yy - (ny - 1) / 2) * res, (xx - (nx - 1) / 2) * res)
    out = {"baseline_median_c": float(np.nanmedian(lst_c)), "valid_fraction": float(clear.mean()),
           "land_fraction": float(valid.sum() / max(clear.sum(), 1))}
    for r in RADII_M:
        ring = lst_c[dist <= r]
        out[f"lst_mean_{r}m_c"] = float(np.nanmean(ring)) if np.isfinite(ring).any() else np.nan
    return out


def scene_rows(item, sites: pd.DataFrame) -> list[dict]:
    """Open a scene's LST and QA bands once and read a window for every venue it covers."""
    rows = []
    item = planetary_computer.sign(item)  # fresh SAS token; long runs outlive the first one
    with rasterio.open(item.assets["lwir11"].href) as lst_src, \
         rasterio.open(item.assets["qa_pixel"].href) as qa_src:
        for s in sites.itertuples():
            st = stats(window(lst_src, s.lat, s.lon, BASELINE_HALF_M),
                       window(qa_src, s.lat, s.lon, BASELINE_HALF_M), lst_src.res[0])
            if st:
                rows.append({"venue_id": s.venue_id, "scene_id": item.id,
                             "acquired_utc": item.datetime, "platform": item.properties["platform"],
                             "scene_cloud_cover": item.properties["eo:cloud_cover"], **st})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, nargs="+", default=[2021, 2022, 2023, 2024, 2025])
    a = ap.parse_args()

    v = venues()
    # Remote (out-of-region) soccer venues only have city-level points; skip.
    sites = v[v.region != "remote"].drop_duplicates("venue_id").reset_index(drop=True)

    # Which scenes cover which venues (venues in the same Landsat path/row share scenes).
    items, covers = {}, {}
    pts = [(s.Index, Point(s.lon, s.lat)) for s in sites.itertuples()]
    for it in search(sites, a.years):
        footprint = shape(it.geometry)
        inside = [i for i, p in pts if footprint.contains(p)]
        if inside:
            items[it.id], covers[it.id] = it, inside
    print(f"{len(items)} scenes for {len(sites)} venues", flush=True)

    def run(sid):
        # GDAL settings for cloud-optimised GeoTIFFs over HTTP: skip directory listing,
        # merge adjacent byte ranges, cache blocks shared by nearby venues.
        with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES",
                          GDAL_HTTP_MULTIRANGE="YES", VSI_CACHE="TRUE", GDAL_CACHEMAX=512):
            return scene_rows(items[sid], sites.loc[covers[sid]])

    rows = []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(run, sid): sid for sid in items}
        for i, fut in enumerate(as_completed(futures), 1):
            try:
                rows += fut.result()
            except Exception as e:  # noqa: BLE001 -- one bad scene shouldn't kill the run
                print(f"  skip {futures[fut]}: {e}", flush=True)
            if i % 10 == 0:
                print(f"  {i}/{len(items)} scenes, {len(rows)} venue-scene rows", flush=True)
    df = pd.DataFrame(rows)
    df["lst_anomaly_500m_c"] = df.lst_mean_500m_c - df.baseline_median_c
    write_bronze(df, "landsat_lst")


if __name__ == "__main__":
    main()
