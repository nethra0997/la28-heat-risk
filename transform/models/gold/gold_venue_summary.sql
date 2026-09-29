-- One row per venue for the map and the AI briefs.
select
    venue_id,
    any_value(venue_name)                                  as venue_name,
    any_value(zone)                                        as zone,
    any_value(exposure)                                    as exposure,
    any_value(region)                                      as region,
    any_value(lat)                                         as lat,
    any_value(lon)                                         as lon,
    string_agg(distinct sport, ', ' order by sport)        as sports,
    count(*)                                               as n_sessions,
    count(*) filter (where medal = 'gold')                 as n_gold_medal_sessions,
    min(session_date)                                      as first_session_date,
    max(session_date)                                      as last_session_date,
    max(risk_score)                                        as max_session_risk_score,
    avg(risk_score)                                        as avg_session_risk_score,
    max(athlete_wbgt_p90_c)                                as worst_session_athlete_wbgt_p90_c,
    max(arrival_wbgt_p90_c)                                as worst_arrival_wbgt_p90_c,
    max(p_black)                                           as worst_session_p_black,
    count(*) filter (where p90_flag in ('red', 'black'))   as n_sessions_red_or_black_p90,
    arg_max(sport || ' ' || strftime(session_date, '%b %d') || ' ' || start_time, risk_score)
                                                           as riskiest_session,
    any_value(svi_overall_pctile)                          as svi_overall_pctile,
    any_value(share_65_plus)                               as share_65_plus,
    any_value(share_hh_no_vehicle)                         as share_hh_no_vehicle,
    any_value(est_population_3km)                          as est_population_3km,
    any_value(lst_500m_median_c)                           as lst_500m_median_c,
    any_value(lst_anomaly_500m_c)                          as lst_anomaly_500m_c,
    any_value(ozone_aqi_p90)                               as ozone_aqi_p90,
    any_value(share_days_ozone_aqi_gt_100)                 as share_days_ozone_aqi_gt_100
from {{ ref('gold_session_risk') }}
where venue_id is not null
group by venue_id
