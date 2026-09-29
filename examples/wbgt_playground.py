"""Play with the WBGT calculator: change the inputs below, run, and watch WBGT respond.

Usage:  uv run python -m examples.wbgt_playground
"""

from heatrisk.wbgt import wbgt, wind_at_2m

# ---- change these ---------------------------------------------------------
air_temp_c = 32.0     # Ta, °C
humidity_pct = 40.0   # relative humidity, %
wind_10m_ms = 2.0     # wind at 10 m, m/s (converted to 2 m below)
sunlight_wm2 = 850.0  # shortwave radiation, W/m²; 0 = night or full shade
sun_height = 0.9      # cos(zenith): 1 = sun straight overhead, 0 = sun on the horizon
direct_share = 0.8    # fraction of sunlight that is direct beam (0.8 = clear sky)
pressure_hpa = 1010.0
# ---------------------------------------------------------------------------

u2 = wind_at_2m(wind_10m_ms)
r = wbgt([air_temp_c], [humidity_pct], [pressure_hpa], [u2],
         [sunlight_wm2], [sun_height], [direct_share]).iloc[0]

print(f"wind at 2 m        : {float(u2):5.2f} m/s")
print(f"globe      Tg      : {r.globe_temp_c:5.1f} °C")
print(f"wet bulb   Tnwb    : {r.natural_wet_bulb_c:5.1f} °C")
print(f"air        Ta      : {air_temp_c:5.1f} °C")
print(f"WBGT = 0.7×{r.natural_wet_bulb_c:.1f} + 0.2×{r.globe_temp_c:.1f} + 0.1×{air_temp_c:.1f}"
      f" = {r.wbgt_c:.1f} °C")

for flag, low in [("black", 32.2), ("red", 31.1), ("yellow", 29.4), ("green", 26.7)]:
    if r.wbgt_c >= low:
        print(f"flag: {flag}")
        break
else:
    print("flag: none")
