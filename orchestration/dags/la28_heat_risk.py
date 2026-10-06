"""LA28 heat-risk pipeline DAGs.

Airflow runs in its own virtualenv (orchestration/.venv) and shells out to the
project env with `uv run`, so Airflow's pinned dependencies never collide with
dbt / geopandas / rasterio. Each task is idempotent: extractors overwrite their
bronze parquet file, dbt rebuilds tables.

  la28_baseline   monthly  schedule PDF, venues, 11 summers of weather, Landsat,
                           air quality, community data -> dbt -> exports -> AI briefs
  la28_forecast   daily    NWS 7-day forecast -> forecast models -> exports.
                           Also triggered whenever the baseline asset updates.
"""

from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import Asset, dag, task_group
from airflow.timetables.assets import AssetOrTimeSchedule
from airflow.timetables.trigger import CronTriggerTimetable

PROJECT = Path(os.getenv("LA28_PROJECT_DIR", Path(__file__).resolve().parents[2]))
UV = os.getenv("LA28_UV") or shutil.which("uv") or "/opt/homebrew/bin/uv"
# Run in the project's own environment, not Airflow's.
ENV = {"PATH": f"{Path(UV).parent}:/usr/bin:/bin", "HOME": os.environ.get("HOME", "")}

WAREHOUSE = Asset(f"file://{PROJECT}/data/warehouse.duckdb")
BASELINE_BUILT = Asset("la28_baseline_built")  # emitted only by the baseline dbt build
GOLD_EXPORTS = Asset(f"file://{PROJECT}/data/gold")

DEFAULT_ARGS = {
    "owner": "la28-heat-risk",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}


def py(task_id: str, module: str, args: str = "", **kw) -> BashOperator:
    return BashOperator(
        task_id=task_id,
        bash_command=f'cd "{PROJECT}" && "{UV}" run --frozen python -m {module} {args}',
        env=ENV, append_env=True, **kw,
    )


def dbt(task_id: str, cmd: str, **kw) -> BashOperator:
    return BashOperator(
        task_id=task_id,
        bash_command=f'cd "{PROJECT}/transform" && "{UV}" run --frozen dbt {cmd} --profiles-dir .',
        env=ENV, append_env=True, **kw,
    )


@dag(
    dag_id="la28_baseline",
    description="Historical heat-risk baseline for every LA28 session",
    schedule="@monthly",
    start_date=datetime(2026, 9, 1, tzinfo=UTC),
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["la28", "baseline"],
)
def la28_baseline():
    schedule = py("parse_schedule_pdf", "ingestion.schedule_pdf")
    venues = py("geocode_venues", "ingestion.venues")

    @task_group(group_id="extract")
    def extract():
        py("weather_history", "ingestion.open_meteo", execution_timeout=timedelta(hours=2))
        py("landsat_lst", "ingestion.landsat_lst", execution_timeout=timedelta(hours=3))
        py("air_quality", "ingestion.air_quality", execution_timeout=timedelta(hours=1))
        py("community", "ingestion.community")

    seed = dbt("dbt_seed", "seed")
    build = dbt("dbt_build", "build --exclude slv_forecast_wbgt+",
                outlets=[WAREHOUSE, BASELINE_BUILT])
    export = py("export_gold", "heatrisk.export", outlets=[GOLD_EXPORTS])
    briefs = py("generate_briefs", "ai.briefs", execution_timeout=timedelta(hours=1))

    schedule >> venues >> extract() >> seed >> build >> export >> briefs


@dag(
    dag_id="la28_forecast",
    description="Refresh 7-day NWS forecast WBGT at every venue",
    # Daily at 06:00 UTC, and whenever the baseline warehouse is rebuilt.
    schedule=AssetOrTimeSchedule(
        timetable=CronTriggerTimetable("0 6 * * *", timezone="UTC"),
        assets=BASELINE_BUILT,
    ),
    start_date=datetime(2026, 9, 1, tzinfo=UTC),
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["la28", "forecast"],
)
def la28_forecast():
    nws = py("nws_forecast", "ingestion.nws_forecast")
    build = dbt("dbt_build_forecast", "build --select slv_forecast_wbgt+", outlets=[WAREHOUSE])
    export = py("export_gold", "heatrisk.export", outlets=[GOLD_EXPORTS])
    nws >> build >> export


la28_baseline()
la28_forecast()
