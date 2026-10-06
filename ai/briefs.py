"""Stage 9: a plain-English heat safety brief for every venue, written by an LLM.

Input:  the gold tables in data/warehouse.duckdb (run dbt build first)
Output: data/gold/venue_briefs.json

The LLM only *writes*: every number comes from the gold tables and is handed to it as a
JSON fact sheet. After generation, a grounding check pulls every number out of the brief
and confirms it appears in the fact sheet. Briefs quoting numbers we didn't supply are
flagged ("grounded": false) rather than silently shipped.

Backends (set LA28_LLM in .env):
  ollama  (default) runs locally and free. Model from LA28_OLLAMA_MODEL (default llama3:instruct)
  claude  Anthropic API; needs ANTHROPIC_API_KEY in .env. Model from LA28_CLAUDE_MODEL.

Usage:  uv run python -m ai.briefs [--venue la_coliseum] [--limit 5]
"""

import argparse
import json
import math
import os
import re
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pandas as pd
from dotenv import load_dotenv

load_dotenv()  # reads .env (never committed) into environment variables

WAREHOUSE = Path("data/warehouse.duckdb")
OUT = Path("data/gold/venue_briefs.json")

SYSTEM = """You write short heat-safety briefs for Olympic venue operations staff.
Rules:
- Use ONLY the facts in the JSON you are given. Never invent numbers, dates, or places.
- Temperatures are WBGT (Wet Bulb Globe Temperature) in degrees C unless labelled otherwise.
  Give degrees F in brackets only where a *_f field provides it; never convert units yourself.
- Flag scale (US Army TB MED 507): green >=26.7C, yellow >=29.4C, red >=31.1C, black >=32.2C.
- p90 means "a hot but not extreme day": 1 in 10 comparable historical days were hotter.
- Indoor venues: athletes are in climate control; focus on spectators arriving outdoors.
- Write 120-180 words, then exactly 3 bullet-point actions. Plain language, no hype.
- The social vulnerability rank is a percentile of census tracts (CDC SVI), NOT a share of
  people and NOT a heat measurement. Say e.g. "the surrounding neighbourhood ranks more
  vulnerable than N% of California census tracts", with N taken from the facts.
- The *_pct neighbourhood fields are shares of the population (e.g. people aged 65+), not
  of households, unless the field name says households.
- If a fact is null or missing, say that data is not available for this venue. Never fill
  the gap with a number from these instructions or from general knowledge.
- this_week_forecast_not_games_time is this week's real forecast, not the 2028 Games. If you
  mention it, give its real dates and say it is the current forecast.
- Do not give medical advice beyond standard heat precautions."""

TEMPLATE = """Write the heat safety brief for this venue.

FACTS:
{facts}
"""


def c_to_f(c):
    return None if c is None or (isinstance(c, float) and math.isnan(c)) else round(c * 9 / 5 + 32, 1)


def clean(v):
    """Round floats to 1 decimal, turn NaN into None and dates into text, so the JSON is tidy."""
    if isinstance(v, float):
        return None if math.isnan(v) else round(v, 1)
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


def pct(v):
    return clean(v * 100) if v is not None and not (isinstance(v, float) and math.isnan(v)) else None


def fact_sheets(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """One JSON fact sheet per venue, built only from the gold tables."""
    venues = con.sql("select * from gold.gold_venue_summary order by max_session_risk_score desc").df()
    sessions = con.sql("""
        select venue_id, sport, session_date, start_time, end_time, medal, risk_score,
               athlete_wbgt_p90_c, arrival_wbgt_p90_c, p90_flag, p_red_or_worse, p_black
        from gold.gold_session_risk where venue_id is not null and risk_score is not null
    """).df()
    forecast = con.sql("select * from gold.gold_venue_forecast").df()

    sheets = []
    for v in venues.to_dict("records"):
        top = []
        for r in sessions[sessions.venue_id == v["venue_id"]].nlargest(3, "risk_score").to_dict("records"):
            top.append({
                "sport": r["sport"], "date": str(r["session_date"]),
                "time": f"{r['start_time']}-{r['end_time']}", "medal_session": r["medal"],
                "risk_score": clean(r["risk_score"]),
                "athlete_wbgt_p90_c": clean(r["athlete_wbgt_p90_c"]),
                "athlete_wbgt_p90_f": c_to_f(clean(r["athlete_wbgt_p90_c"])),
                "arrival_wbgt_p90_c": clean(r["arrival_wbgt_p90_c"]),
                "arrival_wbgt_p90_f": c_to_f(clean(r["arrival_wbgt_p90_c"])),
                "p90_flag": r["p90_flag"],
                "pct_days_red_or_worse": pct(r["p_red_or_worse"] or 0),
                "pct_days_black": pct(r["p_black"] or 0),
            })
        sheet = {
            "venue": v["venue_name"], "zone": v["zone"], "exposure": v["exposure"],
            "sports": v["sports"], "sessions": int(v["n_sessions"]),
            "games_dates": f"{v['first_session_date']} to {v['last_session_date']}",
            "max_session_risk_score_0_100": clean(v["max_session_risk_score"]),
            "worst_session_athlete_wbgt_p90_c": clean(v["worst_session_athlete_wbgt_p90_c"]),
            "worst_session_athlete_wbgt_p90_f": c_to_f(clean(v["worst_session_athlete_wbgt_p90_c"])),
            "sessions_with_red_or_black_p90": int(v["n_sessions_red_or_black_p90"] or 0),
            "neighbourhood_social_vulnerability_rank_pctile_vs_california_tracts": pct(v["svi_overall_pctile"]),
            "neighbourhood_share_age_65_plus_pct": pct(v["share_65_plus"]),
            "neighbourhood_share_households_no_car_pct": pct(v["share_hh_no_vehicle"]),
            "surface_temp_anomaly_vs_surroundings_c": clean(v["lst_anomaly_500m_c"]),
            "ozone_days_over_aqi_100_pct": pct(v["share_days_ozone_aqi_gt_100"]),
            "riskiest_sessions": top,
        }
        fc = forecast[forecast.venue_id == v["venue_id"]]
        if len(fc):
            # Today's real-world forecast, NOT Games time: the label says so, so the model
            # doesn't present October 2026 weather as July 2028.
            sheet["this_week_forecast_not_games_time"] = [
                {"date": str(r["forecast_date"]), "peak_wbgt_c": clean(r["peak_wbgt_sun_c"]),
                 "peak_wbgt_f": c_to_f(clean(r["peak_wbgt_sun_c"])), "flag": r["forecast_flag"]}
                for r in fc.sort_values("forecast_date").head(7).to_dict("records")]
        sheets.append({"venue_id": v["venue_id"], "facts": sheet})
    return sheets


# --- grounding check: every number in the brief must come from the fact sheet ----------
NUM = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")
# Numbers the rules themselves allow: flag thresholds (°C and °F), list counts, the year,
# and 65 as in "aged 65+" (a label, not a data value).
ALLOWED = {26.7, 29.4, 31.1, 32.2, 80, 85, 88, 90, 1, 2, 3, 10, 65, 100, 507, 2028, 0}


def numbers_in(obj) -> set[float]:
    return {float(x) for x in NUM.findall(json.dumps(obj))}


def ungrounded_numbers(text: str, facts: dict) -> list[str]:
    known = numbers_in(facts) | ALLOWED
    return [tok for tok in NUM.findall(text)
            if not any(abs(float(tok) - k) <= 0.51 for k in known)]  # allow rounding to whole numbers


# --- the two LLM backends ----------------------------------------------------------------
def generate_ollama(prompt: str) -> tuple[str, str]:
    import ollama

    model = os.getenv("LA28_OLLAMA_MODEL") or "llama3:instruct"
    r = ollama.chat(model=model, messages=[{"role": "system", "content": SYSTEM},
                                           {"role": "user", "content": prompt}],
                    options={"temperature": 0.2})  # low temperature = less creative, more literal
    return r["message"]["content"].strip(), f"ollama:{model}"


def generate_claude(prompt: str) -> tuple[str, str]:
    import anthropic

    model = os.getenv("LA28_CLAUDE_MODEL") or "claude-opus-5-5"
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    r = client.beta.messages.create(
        model=model,
        max_tokens=16000,
        output_config={"effort": "low"},  # a short brief from given facts needs little reasoning
        # If the request is declined by a safety filter, retry on a suitable fallback model.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    if r.stop_reason == "refusal":
        raise RuntimeError(f"model declined: {r.stop_details}")
    return "".join(b.text for b in r.content if b.type == "text").strip(), f"anthropic:{r.model}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--venue")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()

    backend = (os.getenv("LA28_LLM") or "ollama").lower()
    gen = generate_claude if backend == "claude" else generate_ollama

    # Read the facts, then release the warehouse: DuckDB allows one writer, and writing is slow.
    with duckdb.connect(str(WAREHOUSE), read_only=True) as con:
        sheets = fact_sheets(con)
    if a.venue:
        sheets = [s for s in sheets if s["venue_id"] == a.venue]
    if a.limit:
        sheets = sheets[: a.limit]

    existing = json.loads(OUT.read_text()) if OUT.exists() else {}
    for s in sheets:
        text, model = gen(TEMPLATE.format(facts=json.dumps(s["facts"], indent=1)))
        bad = ungrounded_numbers(text, s["facts"])
        existing[s["venue_id"]] = {
            "venue_id": s["venue_id"], "brief": text, "model": model,
            "ungrounded_numbers": bad, "grounded": not bad, "facts": s["facts"],
            "generated_at": datetime.now(UTC).isoformat(),
        }
        print(f"{s['venue_id']}: {'ok' if not bad else 'CHECK ' + ', '.join(bad)}", flush=True)
        OUT.write_text(json.dumps(existing, indent=1, default=str))  # save after each venue


if __name__ == "__main__":
    main()
