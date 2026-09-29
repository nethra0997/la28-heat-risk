-- The headline table: one row per session with a transparent 0-100 composite risk score.
-- Each component is scaled to 0-100 with a documented linear ramp, then weighted
-- (weights in seeds/risk_weights.csv). Missing components drop out and the remaining
-- weights are renormalised, so a venue without e.g. air-quality monitors isn't zeroed.

with w as (
    select
        max(weight) filter (where component = 'athlete_heat')   as w_athlete,
        max(weight) filter (where component = 'spectator_heat') as w_spectator,
        max(weight) filter (where component = 'community')      as w_community,
        max(weight) filter (where component = 'surface_heat')   as w_surface,
        max(weight) filter (where component = 'air_quality')    as w_air
    from {{ ref('risk_weights') }}
),

base as (
    select
        s.*,
        h.n_analog_days,
        h.athlete_wbgt_median_c,
        h.athlete_wbgt_p90_c,
        h.athlete_wbgt_max_c,
        h.arrival_wbgt_p90_c,
        h.peak_temp_median_c,
        h.p_yellow_or_worse,
        h.p_red_or_worse,
        h.p_black,
        coalesce(h.p90_flag, case when s.exposure = 'indoor' then 'indoor' end) as p90_flag,
        h.p90_flag_rank,
        c.svi_overall_pctile,
        c.share_65_plus,
        c.share_hh_no_vehicle,
        c.est_population_3km,
        sh.lst_500m_median_c,
        sh.lst_anomaly_500m_c,
        aq.ozone_aqi_p90,
        aq.share_days_ozone_aqi_gt_100
    from {{ ref('slv_sessions') }} s
    left join {{ ref('gold_session_heat') }} h using (session_id)
    left join {{ ref('slv_venue_community') }} c using (venue_id)
    left join {{ ref('slv_venue_surface_heat') }} sh using (venue_id)
    left join {{ ref('slv_venue_air_quality') }} aq using (venue_id)
),

scored as (
    select
        *,
        -- 20 C WBGT (no concern) -> 0 ; 32.2 C (black flag) -> 100
        {{ ramp('athlete_wbgt_p90_c', 20, 32.2) }}                   as score_athlete_heat,
        {{ ramp('arrival_wbgt_p90_c', 20, 32.2) }}                   as score_spectator_heat,
        svi_overall_pctile * 100                                     as score_community,
        -- -5 C (cool spot) -> 0 ; +5 C (heat island) -> 100
        {{ ramp('lst_anomaly_500m_c', -5, 5) }}                      as score_surface_heat,
        -- 0% of days -> 0 ; 20%+ of days over AQI 100 -> 100
        {{ ramp('share_days_ozone_aqi_gt_100', 0, 0.2) }}            as score_air_quality
    from base
)

select
    scored.*,
    -- No heat component (indoor-only or untimed session) -> no score, rather than a
    -- misleadingly low one built from context alone.
    case when score_athlete_heat is null and score_spectator_heat is null then null else round(
        ( coalesce(score_athlete_heat * w_athlete, 0)
        + coalesce(score_spectator_heat * w_spectator, 0)
        + coalesce(score_community * w_community, 0)
        + coalesce(score_surface_heat * w_surface, 0)
        + coalesce(score_air_quality * w_air, 0) )
      / nullif( case when score_athlete_heat   is not null then w_athlete   else 0 end
              + case when score_spectator_heat is not null then w_spectator else 0 end
              + case when score_community      is not null then w_community else 0 end
              + case when score_surface_heat   is not null then w_surface   else 0 end
              + case when score_air_quality    is not null then w_air       else 0 end, 0)
    , 1) end                                                                 as risk_score,
    ( case when score_athlete_heat   is not null then w_athlete   else 0 end
    + case when score_spectator_heat is not null then w_spectator else 0 end
    + case when score_community      is not null then w_community else 0 end
    + case when score_surface_heat   is not null then w_surface   else 0 end
    + case when score_air_quality    is not null then w_air       else 0 end) as weight_coverage
from scored
cross join w
