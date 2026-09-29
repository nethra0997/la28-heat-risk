"""Shared paths, config and helpers for extractors.

Every extractor lands raw-but-tabular data in data/bronze/<name>.parquet.
dbt reads those files as sources; nothing downstream touches the APIs.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
BRONZE = DATA / "bronze"
WAREHOUSE = DATA / "warehouse.duckdb"
SEEDS = ROOT / "transform" / "seeds"

load_dotenv(ROOT / ".env")

USER_AGENT = "la28-heat-risk (portfolio project; github.com/)"


def env(name: str, required: bool = False) -> str | None:
    val = os.getenv(name) or None
    if required and not val:
        raise RuntimeError(f"Set {name} in .env (see .env.example)")
    return val


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, max=30), reraise=True)
def get_json(url: str, params: dict | None = None, headers: dict | None = None) -> dict | list:
    h = {"User-Agent": USER_AGENT, **(headers or {})}
    r = requests.get(url, params=params, headers=h, timeout=60)
    r.raise_for_status()
    return r.json()


def write_bronze(df: pd.DataFrame, name: str) -> Path:
    """Write a bronze table with load metadata. Overwrites: extractors are idempotent."""
    BRONZE.mkdir(parents=True, exist_ok=True)
    df = df.copy()
    df["_loaded_at"] = datetime.now(UTC)
    path = BRONZE / f"{name}.parquet"
    df.to_parquet(path, index=False)
    return path


def venues() -> pd.DataFrame:
    """Geocoded venue reference (output of ingestion.venues)."""
    return pd.read_parquet(BRONZE / "venues.parquet")
