# LA28 Heat Risk

**What will it feel like at the 2028 Olympic Games, and what should people bring?**

An end-to-end data pipeline that combines 11 summers of hourly weather, the official LA28
schedule, satellite surface temperature, air quality and census data into a plain-language
guide to conditions at every venue and session of the LA28 Games (July 10–30, 2028).

- **Dashboard:** [Tableau Public](https://public.tableau.com/views/LA28HeatRiskAFansGuidetoConditionsatthe2028Olympics/LA28-At-A-Glance) (2 pages: *At a glance* and *Plan your visit*)
- **Full report:** [docs/LA28_Heat_Risk_Project_Report.pdf](docs/LA28_Heat_Risk_Project_Report.pdf)

## Findings

- **LA is almost always dry; the soccer cities are not.** Rain falls on 1–2% of July afternoons at LA
  venues, but on 29–40% in Nashville, Columbus, New York and St. Louis.
- **The coast runs about 10 °F cooler than inland LA**: a typical afternoon is 79 °F at Alamitos Beach
  and 90 °F at the Rose Bowl and Santa Anita.
- **The final week is the toughest.** Sessions likely to be hot or very hot go from 0–1 a day before
  July 22 to 3–5 a day from July 22 to 29.
- **Afternoon softball in Oklahoma City** is the hardest event to attend: typically 94–95 °F, about
  100 °F on a hot day.

## Architecture

```
7 public sources ──► Python extractors ──► bronze (Parquet) ──► dbt + DuckDB ──► gold CSVs ──► Tableau
                                                                 staging → silver → gold      └► LLM briefs
                      └──────────────── orchestrated by Apache Airflow (monthly + daily DAGs) ────────────┘
```

| Layer | Tools | Where |
|---|---|---|
| Extraction | Python, requests, pdfplumber, geopandas, pystac-client, rasterio | [ingestion/](ingestion) |
| Warehouse and transforms | DuckDB, dbt (20 models, 4 seeds, 52 data tests) | [transform/](transform) |
| Heat physics | Liljegren (2008) WBGT model in numpy, 9 unit tests | [heatrisk/wbgt.py](heatrisk/wbgt.py) |
| Orchestration | Apache Airflow 3.3: monthly baseline and daily forecast DAGs | [orchestration/dags](orchestration/dags) |
| AI | LLM venue briefs (Ollama or Claude) with an automatic number check | [ai/briefs.py](ai/briefs.py) |
| Presentation | Tableau Public from CSV exports | [data/gold](data/gold) |

## Data sources

| Source | Format | Used for |
|---|---|---|
| [LA28 competition schedule v3.1](https://la28.org/en/games-plan.html) | PDF, parsed from its drawn grid | 854 sessions: venue, sport, date, time, medal |
| [Open-Meteo historical weather](https://open-meteo.com/en/docs/historical-weather-api) | JSON API | Hourly weather, July 1–Aug 15, 2015–2025, 40 places |
| [NWS forecast](https://www.weather.gov/documentation/services-web-api) | JSON API (two chained calls) | 7-day hourly forecast per venue |
| [EPA AirData](https://aqs.epa.gov/aqsweb/airdata/download_files.html) | Bulk zipped CSVs | Ozone and PM2.5 at monitors within 25 km |
| [CDC/ATSDR SVI](https://www.atsdr.cdc.gov/place-health/php/svi/) + [Census tracts](https://www.census.gov/geographies/mapping-files/time-series/geo/cartographic-boundary.html) | CSV + shapefile, spatial join | Vulnerability of neighbourhoods within 3 km |
| [Landsat 8/9](https://planetarycomputer.microsoft.com/dataset/landsat-c2-l2) | Satellite rasters (STAC) | Local heat islands at 30 m |
| [OpenStreetMap Nominatim](https://nominatim.openstreetmap.org/) | Geocoding API | Venue coordinates |

## Method in brief

1. **Heat stress, not temperature.** Every hour is converted to WBGT (Wet Bulb Globe Temperature), which
   combines humidity, sun, wind and air temperature, using the model behind US National Weather Service
   WBGT tools.
2. **Analog days.** Each session is matched to the same clock hours on the same date ±3 days in each of
   11 past summers (~77 comparable days); a "hot day" is the 90th percentile.
3. **Plain language.** Results become comfort levels (Comfortable / Warm / Hot / Very hot / Indoors),
   °F temperatures, chance of rain, and rule-based advice on what to bring.

These are patterns from past summers, not a forecast. See the [report](docs/LA28_Heat_Risk_Project_Report.pdf)
for every source, transformation, test and limitation.

## Run it

```bash
uv sync         # Python environment from uv.lock
make extract    # 7 extractors -> data/bronze
make dbt        # build and test the warehouse
make export     # gold tables -> data/gold/*.csv
make briefs     # AI venue briefs (local Ollama by default; see .env.example)
make airflow    # Airflow UI at http://localhost:8080
```

## How this repo was built

The `main` branch was built in stages, one commit per stage, from a first API call to orchestration
and AI. The `reference` branch holds the first complete version for comparison.

*Independent project, not affiliated with LA28, the IOC or the USOPC.*
