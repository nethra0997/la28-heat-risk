SHELL := /bin/bash
UV := uv run
# Airflow lives in its own environment (orchestration/.venv) and keeps its settings,
# database and logs in orchestration/airflow_home/.
# PATH: `airflow standalone` starts its parts by running `airflow` by name, so Airflow's
# environment must be on the PATH.
AIRFLOW_ENV := PATH=$(CURDIR)/orchestration/.venv/bin:$$PATH \
               AIRFLOW_HOME=$(CURDIR)/orchestration/airflow_home \
               AIRFLOW__CORE__DAGS_FOLDER=$(CURDIR)/orchestration/dags \
               AIRFLOW__CORE__LOAD_EXAMPLES=False
AIRFLOW := $(AIRFLOW_ENV) orchestration/.venv/bin/airflow

.PHONY: setup airflow-setup extract dbt export briefs all forecast test airflow airflow-test

setup:            ## project env (pipeline, dbt)
	uv sync

airflow-setup:    ## separate Airflow env, pinned with the official constraints file
	uv venv orchestration/.venv --python 3.12
	uv pip install --python orchestration/.venv "apache-airflow==3.3.2" \
	  --constraint https://raw.githubusercontent.com/apache/airflow/constraints-3.3.2/constraints-3.12.txt
	$(AIRFLOW) db migrate

extract:          ## all extractors (same order as the la28_baseline DAG)
	$(UV) python -m ingestion.schedule_pdf
	$(UV) python -m ingestion.venues
	$(UV) python -m ingestion.open_meteo
	$(UV) python -m ingestion.landsat_lst
	$(UV) python -m ingestion.air_quality
	$(UV) python -m ingestion.community
	$(UV) python -m ingestion.nws_forecast

dbt:              ## build and test every dbt model
	cd transform && $(UV) dbt build --profiles-dir .

export:           ## gold tables -> data/gold/*.csv
	$(UV) python -m heatrisk.export

briefs:           ## AI venue briefs (local Ollama by default; see .env.example)
	$(UV) python -m ai.briefs

all: extract dbt export briefs

forecast:         ## refresh just the 7-day forecast
	$(UV) python -m ingestion.nws_forecast
	cd transform && $(UV) dbt build --profiles-dir . --select slv_forecast_wbgt+
	$(UV) python -m heatrisk.export

test:             ## python unit tests + dbt data tests
	$(UV) pytest -q
	cd transform && $(UV) dbt test --profiles-dir .

airflow:          ## Airflow UI at http://localhost:8080 (login printed on first start)
	$(AIRFLOW) standalone

airflow-test:     ## run the forecast DAG once, without the scheduler or UI
	$(AIRFLOW) dags test la28_forecast
