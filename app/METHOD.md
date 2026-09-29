### How the score works

**WBGT.** Wet Bulb Globe Temperature is the heat-stress index sports medicine and the military
use. It combines air temperature, humidity, wind and sun. We compute it hourly with the
Liljegren et al. (2008) model from Open-Meteo's ERA5-based reanalysis.
Outdoor venues use sun WBGT. Covered venues (SoFi Stadium) use shade WBGT. Indoor athletes
are not scored.

**Analog days.** For each session we take the same clock hours on the same calendar date
±3 days in each summer from 2015 to 2025, which gives about 77 comparable days. *p90* is the
peak WBGT that 1 in 10 of those days exceeded.

**Flags** (US Army TB MED 507): green ≥ 26.7 °C, yellow ≥ 29.4 °C, red ≥ 31.1 °C,
black ≥ 32.2 °C.

**Composite risk (0–100)** is a weighted sum of scaled components. The weights are in
`transform/seeds/risk_weights.csv`.

| Component | Weight | 0 → 100 |
|---|---|---|
| Athlete heat (p90 peak WBGT) | 0.35 | 20 °C → 32.2 °C |
| Spectator arrival heat (p90 WBGT the hour before) | 0.25 | 20 °C → 32.2 °C |
| Community vulnerability (SVI, 3 km) | 0.20 | percentile |
| Surface heat island (Landsat LST anomaly) | 0.10 | −5 °C → +5 °C |
| Air quality (share of days with ozone AQI > 100) | 0.10 | 0 → 20 % |

When a component is missing, the remaining weights are renormalised.

**Limits.** Reanalysis grid cells are about 9–25 km wide, so stadium microclimates are not
resolved. The weights are a judgement call. Nothing here is medical advice.
