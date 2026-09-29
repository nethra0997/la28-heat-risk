# LA28 Heat Risk

Heat-illness risk for every LA28 Olympic venue and session, scored with WBGT (Wet Bulb Globe
Temperature) and presented in a Tableau dashboard.

**This branch is a step-by-step rebuild.** I'm rebuilding the project one stage per commit to
learn how each piece works: data ingestion, warehousing, dbt, Airflow and AI. The finished
project lives on the [`reference`](../../tree/reference) branch.

## Stages

- [x] **0. Setup:** Python environment with `uv`, `pyproject.toml`, `uv.lock`
- [ ] **1. First API pull:** one week of weather for one venue, saved as Parquet
- [ ] **2. Scale up:** all venues, 11 summers (the bronze layer)
- [ ] **3. The metric:** WBGT physics and unit tests
- [ ] **4. Warehouse:** DuckDB and SQL on Parquet
- [ ] **5. dbt:** staging, silver and gold models, seeds and tests
- [ ] **6. First Tableau view:** peak WBGT by venue
- [ ] **7. Other data types:** schedule PDF, Landsat raster, EPA air quality, census/SVI
- [ ] **8. Airflow:** orchestrating the pipeline as a DAG
- [ ] **9. AI:** LLM-written venue briefs with a grounding check
- [ ] **10. Final Tableau dashboard**

## Run it

```bash
uv sync     # build the environment from uv.lock
```
