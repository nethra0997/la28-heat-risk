SHELL := /bin/bash
UV := uv run
AIRFLOW_ENV := AIRFLOW_HOME=$(CURDIR)/orchestration/airflow_home \
               AIRFLOW__CORE__DAGS_FOLDER=$(CURDIR)/orchestration/dags \
               AIRFLOW__CORE__LOAD_EXAMPLES=False
AIRFLOW := $(AIRFLOW_ENV) orchestration/.venv/bin/airflow

.PHONY: setup airflow-setup extract dbt export briefs all test app airflow forecast

setup:            ## project env (pipeline, dbt, app)
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

dbt:
	cd transform && $(UV) dbt seed --profiles-dir . && $(UV) dbt build --profiles-dir .

export:
	$(UV) python -m heatrisk.export

briefs:
	$(UV) python -m ai.briefs

all: extract dbt export briefs

forecast:         ## refresh just the 7-day forecast
	$(UV) python -m ingestion.nws_forecast
	cd transform && $(UV) dbt build --profiles-dir . --select slv_forecast_wbgt+
	$(UV) python -m heatrisk.export

test:
	$(UV) pytest -q
	cd transform && $(UV) dbt test --profiles-dir .

app:
	$(UV) streamlit run app/streamlit_app.py

airflow:          ## Airflow UI at http://localhost:8080 (login printed on first start)
	$(AIRFLOW) standalone
