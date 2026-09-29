"""Generate a plain-English heat safety brief for every venue.

The LLM only *writes*: all numbers come from the gold tables and are passed in as a
JSON fact sheet. After generation a grounding check pulls every number out of the
brief and confirms it appears in the fact sheet; briefs that cite numbers we didn't
supply are flagged (and shown with a warning in the app) rather than silently shipped.

Backends (env LA28_LLM):
  ollama  (default) local, free. Model from LA28_OLLAMA_MODEL (default llama3:instruct)
  claude  Anthropic API, needs ANTHROPIC_API_KEY. Model from LA28_CLAUDE_MODEL.

Usage:  uv run python -m ai.briefs [--venue sofi_stadium] [--limit 5]
"""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import UTC, datetime

import duckdb
import pandas as pd

from ingestion.common import DATA, WAREHOUSE, env

OUT = DATA / "gold" / "venue_briefs.json"

SYSTEM = """You write short heat-safety briefs for Olympic venue operations staff.
Rules:
- Use ONLY the facts in the JSON you are given. Never invent numbers, dates, or places.
- Temperatures are WBGT (Wet Bulb Globe Temperature) in degrees C unless labelled otherwise.
  Also give degrees F in brackets for WBGT flag values, using the *_f fields provided.
- Flag scale (US Army TB MED 507): green >=26.7C, yellow >=29.4C, red >=31.1C, black >=32.2C.
- p90 means "a hot but not extreme day": 1 in 10 comparable historical days were hotter.
- Indoor venues: athletes are in climate control; focus on spectators arriving outdoors.
- Write 120-180 words, then exactly 3 bullet-point actions. Plain language, no hype.
- The social vulnerability rank is a percentile of census tracts (CDC SVI), NOT a share of
  people and NOT a heat measurement. Say e.g. "the surrounding neighbourhood ranks more
  vulnerable than 59% of California census tracts".
- Do not give medical advice beyond standard heat precautions."""

TEMPLATE = """Write the heat safety brief for this venue.

FACTS:
{facts}
"""


def c_to_f(c):
    return None if c is None or (isinstance(c, float) and math.isnan(c)) else round(c * 9 / 5 + 32, 1)


def clean(v):
    if isinstance(v, float):
        return None if math.isnan(v) else round(v, 1)
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


def fact_sheets(con: duckdb.DuckDBPyConnection) -> list[dict]:
    venues = con.sql("select * from gold.gold_venue_summary order by max_session_risk_score desc").df()
    sessions = con.sql("""
        select venue_id, sport, session_date, start_time, end_time, medal, risk_score,
               athlete_wbgt_p90_c, arrival_wbgt_p90_c, p90_flag, p_red_or_worse, p_black
        from gold.gold_session_risk where venue_id is not null and risk_score is not null
    """).df()
    try:
        forecast = con.sql("select * from gold.gold_venue_forecast").df()
    except duckdb.CatalogException:
        forecast = pd.DataFrame(columns=["venue_id"])

    sheets = []
    for v in venues.to_dict("records"):
        s = sessions[sessions.venue_id == v["venue_id"]].nlargest(3, "risk_score")
        top = []
        for r in s.to_dict("records"):
            top.append({
                "sport": r["sport"], "date": str(r["session_date"]),
                "time": f"{r['start_time']}-{r['end_time']}", "medal_session": r["medal"],
                "risk_score": clean(r["risk_score"]),
                "athlete_wbgt_p90_c": clean(r["athlete_wbgt_p90_c"]),
                "athlete_wbgt_p90_f": c_to_f(clean(r["athlete_wbgt_p90_c"])),
                "arrival_wbgt_p90_c": clean(r["arrival_wbgt_p90_c"]),
                "p90_flag": r["p90_flag"],
                "pct_days_red_or_worse": clean((r["p_red_or_worse"] or 0) * 100),
                "pct_days_black": clean((r["p_black"] or 0) * 100),
            })
        fc = forecast[forecast.venue_id == v["venue_id"]]
        sheet = {
            "venue": v["venue_name"], "zone": v["zone"], "exposure": v["exposure"],
            "sports": v["sports"], "sessions": int(v["n_sessions"]),
            "games_dates": f"{v['first_session_date']} to {v['last_session_date']}",
            "max_session_risk_score_0_100": clean(v["max_session_risk_score"]),
            "worst_session_athlete_wbgt_p90_c": clean(v["worst_session_athlete_wbgt_p90_c"]),
            "worst_session_athlete_wbgt_p90_f": c_to_f(clean(v["worst_session_athlete_wbgt_p90_c"])),
            "sessions_with_red_or_black_p90": int(v["n_sessions_red_or_black_p90"] or 0),
            "neighbourhood_social_vulnerability_rank_pctile_vs_california_tracts": clean((v["svi_overall_pctile"] or float("nan")) * 100),
            "neighbourhood_share_age_65_plus_pct": clean((v["share_65_plus"] or float("nan")) * 100),
            "neighbourhood_share_households_no_car_pct":
                clean((v["share_hh_no_vehicle"] or float("nan")) * 100),
            "surface_temp_anomaly_vs_surroundings_c": clean(v["lst_anomaly_500m_c"]),
            "ozone_days_over_aqi_100_pct":
                clean((v["share_days_ozone_aqi_gt_100"] or float("nan")) * 100),
            "riskiest_sessions": top,
        }
        if len(fc):
            sheet["next_days_forecast"] = [
                {"date": str(r["forecast_date"]), "peak_wbgt_c": clean(r["peak_wbgt_sun_c"]),
                 "flag": r["forecast_flag"]}
                for r in fc.sort_values("forecast_date").head(7).to_dict("records")]
        sheets.append({"venue_id": v["venue_id"], "facts": sheet})
    return sheets


# --- grounding check ---------------------------------------------------------
NUM = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")
ALLOWED = {26.7, 29.4, 31.1, 32.2, 80, 85, 88, 90, 1, 2, 3, 10, 100, 507, 2028, 0}


def numbers_in(obj) -> set[float]:
    return {float(x) for x in NUM.findall(json.dumps(obj))}


def ungrounded_numbers(text: str, facts: dict) -> list[str]:
    known = numbers_in(facts) | ALLOWED
    bad = []
    for tok in NUM.findall(text):
        x = float(tok)
        if not any(abs(x - k) <= 0.51 for k in known):  # allow rounding to whole numbers
            bad.append(tok)
    return bad


# --- backends ----------------------------------------------------------------
def generate_ollama(prompt: str) -> tuple[str, str]:
    import ollama

    model = env("LA28_OLLAMA_MODEL") or "llama3:instruct"
    r = ollama.chat(model=model, messages=[{"role": "system", "content": SYSTEM},
                                           {"role": "user", "content": prompt}],
                    options={"temperature": 0.2})
    return r["message"]["content"].strip(), f"ollama:{model}"


def generate_claude(prompt: str) -> tuple[str, str]:
    import anthropic

    model = env("LA28_CLAUDE_MODEL") or "claude-haiku-4-5-20251001"
    client = anthropic.Anthropic()
    r = client.messages.create(model=model, max_tokens=700, temperature=0.2, system=SYSTEM,
                               messages=[{"role": "user", "content": prompt}])
    return "".join(b.text for b in r.content if b.type == "text").strip(), f"anthropic:{model}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--venue")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()

    backend = (env("LA28_LLM") or "ollama").lower()
    gen = generate_claude if backend == "claude" else generate_ollama

    # Read facts and release the file: DuckDB allows one writer, and generation is slow.
    with duckdb.connect(str(WAREHOUSE), read_only=True) as con:
        sheets = fact_sheets(con)
    if a.venue:
        sheets = [s for s in sheets if s["venue_id"] == a.venue]
    if a.limit:
        sheets = sheets[: a.limit]

    existing = json.loads(OUT.read_text()) if OUT.exists() else {}
    for s in sheets:
        prompt = TEMPLATE.format(facts=json.dumps(s["facts"], indent=1))
        text, model = gen(prompt)
        bad = ungrounded_numbers(text, s["facts"])
        existing[s["venue_id"]] = {
            "venue_id": s["venue_id"], "brief": text, "model": model,
            "ungrounded_numbers": bad, "grounded": not bad, "facts": s["facts"],
            "generated_at": datetime.now(UTC).isoformat(),
        }
        print(f"{s['venue_id']}: {'ok' if not bad else 'CHECK ' + ', '.join(bad)}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(existing, indent=1, default=str))


if __name__ == "__main__":
    main()
