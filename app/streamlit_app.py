"""LA28 Heat Risk -- venue map, session explorer and AI heat safety briefs.

Reads the flat gold exports in data/gold/ (no warehouse connection needed), so it
deploys to Streamlit Community Cloud with just the exported files.

Run:  uv run streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pydeck as pdk
import streamlit as st

GOLD = Path(__file__).resolve().parents[1] / "data" / "gold"
FLAG_COLORS = {"none": "#9e9e9e", "green": "#2e7d32", "yellow": "#f9a825", "red": "#c62828",
               "black": "#212121", "indoor": "#5c6bc0"}

st.set_page_config(page_title="LA28 Heat Risk", page_icon=":thermometer:", layout="wide")


@st.cache_data
def load():
    venues = pd.read_parquet(GOLD / "gold_venue_summary.parquet")
    sessions = pd.read_parquet(GOLD / "gold_session_risk.parquet")
    briefs_path = GOLD / "venue_briefs.json"
    briefs = json.loads(briefs_path.read_text()) if briefs_path.exists() else {}
    fc_path = GOLD / "gold_venue_forecast.parquet"
    forecast = pd.read_parquet(fc_path) if fc_path.exists() else pd.DataFrame()
    return venues, sessions, briefs, forecast


def risk_rgb(score: float) -> list[int]:
    """0 -> pale yellow, 100 -> deep red."""
    s = 0 if pd.isna(score) else max(0.0, min(score, 100.0)) / 100
    return [int(255 - 60 * s), int(220 - 200 * s), int(120 - 100 * s), 200]


if not (GOLD / "gold_venue_summary.parquet").exists():
    st.error("No gold exports yet. Run the pipeline: `make all` (or the la28_baseline DAG).")
    st.stop()

venues, sessions, briefs, forecast = load()

st.title("LA28 Heat Risk")
st.caption(
    "Heat-illness risk for every LA28 Olympic session, scored from 11 summers of hourly weather "
    "(Liljegren WBGT), Landsat surface temperature, EPA air quality and CDC/ATSDR social "
    "vulnerability. Historical climatology, not a forecast, unless marked.")

la = venues[venues.region != "remote"]
c1, c2, c3, c4 = st.columns(4)
c1.metric("Sessions scored", f"{sessions.risk_score.notna().sum():,}")
c2.metric("Venues", len(venues))
c3.metric("Sessions with red/black p90 flag", int(sessions.p90_flag.isin(["red", "black"]).sum()))
c4.metric("Hottest session p90 WBGT", f"{sessions.athlete_wbgt_p90_c.max():.1f} °C")

tab_map, tab_sessions, tab_brief, tab_method = st.tabs(
    ["Venue map", "Session explorer", "Heat safety briefs", "Method"])

with tab_map:
    la = la.assign(color=la.max_session_risk_score.map(risk_rgb),
                   radius=300 + la.n_sessions.fillna(0) * 25)
    st.pydeck_chart(pdk.Deck(
        map_style=None,
        initial_view_state=pdk.ViewState(latitude=33.98, longitude=-118.2, zoom=8.6),
        layers=[pdk.Layer("ScatterplotLayer", data=la, get_position="[lon, lat]",
                          get_fill_color="color", get_radius="radius", pickable=True,
                          stroked=True, get_line_color=[40, 40, 40], line_width_min_pixels=1)],
        tooltip={"html": "<b>{venue_name}</b><br/>{sports}<br/>Max session risk: "
                         "{max_session_risk_score}<br/>Worst p90 WBGT: "
                         "{worst_session_athlete_wbgt_p90_c} °C"},
    ))
    st.caption("Colour = highest session risk score at the venue; size = number of sessions.")
    show = ["venue_name", "exposure", "sports", "n_sessions", "max_session_risk_score",
            "worst_session_athlete_wbgt_p90_c", "n_sessions_red_or_black_p90",
            "svi_overall_pctile", "lst_anomaly_500m_c"]
    st.dataframe(venues.sort_values("max_session_risk_score", ascending=False)[show],
                 hide_index=True, width="stretch")

with tab_sessions:
    f1, f2, f3 = st.columns(3)
    sport = f1.multiselect("Sport", sorted(sessions.sport.dropna().unique()))
    exposure = f2.multiselect("Exposure", ["outdoor", "covered", "indoor"], ["outdoor", "covered"])
    medal_only = f3.checkbox("Medal sessions only")
    df = sessions[sessions.risk_score.notna()]
    if sport:
        df = df[df.sport.isin(sport)]
    if exposure:
        df = df[df.exposure.isin(exposure)]
    if medal_only:
        df = df[df.medal.notna()]

    st.subheader("Risk calendar")
    cal = df.groupby(["venue_name", "session_date"]).risk_score.max().reset_index()
    st.vega_lite_chart(cal, {
        "mark": "rect",
        "encoding": {
            "x": {"field": "session_date", "type": "ordinal", "timeUnit": "monthdate",
                  "title": None},
            "y": {"field": "venue_name", "type": "nominal", "title": None,
                  "sort": {"op": "max", "field": "risk_score", "order": "descending"}},
            "color": {"field": "risk_score", "type": "quantitative", "title": "Risk",
                      "scale": {"scheme": "orangered", "domain": [0, 100]}},
            "tooltip": [{"field": "venue_name"}, {"field": "session_date", "type": "temporal"},
                        {"field": "risk_score", "format": ".0f"}],
        },
    }, width="stretch")

    cols = ["session_date", "start_time", "end_time", "venue_name", "sport", "medal", "exposure",
            "risk_score", "athlete_wbgt_median_c", "athlete_wbgt_p90_c", "p90_flag",
            "p_red_or_worse", "arrival_wbgt_p90_c"]
    st.dataframe(df.sort_values("risk_score", ascending=False)[cols], hide_index=True,
                 width="stretch",
                 column_config={"p_red_or_worse": st.column_config.ProgressColumn(
                     "P(red flag or worse)", min_value=0, max_value=1, format="%.2f")})

with tab_brief:
    if not briefs:
        st.info("No briefs yet. Generate them with `uv run python -m ai.briefs`.")
    else:
        names = {v: briefs[v]["facts"]["venue"] for v in briefs}
        pick = st.selectbox("Venue", list(names), format_func=names.get)
        b = briefs[pick]
        if not b["grounded"]:
            st.warning("Grounding check: this brief cites numbers not found in the source data "
                       f"({', '.join(b['ungrounded_numbers'])}). Treat with care.")
        st.markdown(b["brief"])
        st.caption(f"Written by {b['model']} from the fact sheet below · {b['generated_at'][:16]} UTC")
        with st.expander("Fact sheet given to the model"):
            st.json(b["facts"])
        if len(forecast):
            fc = forecast[forecast.venue_id == pick]
            if len(fc):
                st.subheader("Next 7 days (NWS forecast, estimated WBGT)")
                st.bar_chart(fc.set_index("forecast_date")["peak_wbgt_sun_c"])

with tab_method:
    st.markdown(Path(__file__).with_name("METHOD.md").read_text())
