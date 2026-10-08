-- A fan's guide to each venue: what a typical afternoon is like there during the Games window
-- (July 10-30, 2015-2025), in the venue's own local time. Works even where session times are
-- not yet set (most out-of-state soccer), which is exactly where afternoon rain is likely.

with venues as (
    select distinct
        venue_id, venue_name, region, exposure, loc_id, lat, lon,
        -- Local time zone from longitude: enough for these venues (LA, Oklahoma City, St. Louis,
        -- Nashville = Pacific/Central; New York, Columbus = Eastern).
        case when lon > -85  then 'America/New_York'
             when lon > -102 then 'America/Chicago'
             else 'America/Los_Angeles' end                     as tz
    from {{ ref('stg_venues') }}
),

afternoons as (
    -- one row per venue per day: the local afternoon (noon to 6 pm)
    select
        v.venue_id,
        timezone(v.tz, w.time_utc)::date                        as local_date,
        max(w.temp_c)                                           as peak_temp_c,
        sum(w.precip_mm)                                        as rain_mm
    from {{ ref('slv_weather_wbgt') }} w
    join venues v using (loc_id)
    where hour(timezone(v.tz, w.time_utc)) between 12 and 17
      and month(timezone(v.tz, w.time_utc)) = 7
      and day(timezone(v.tz, w.time_utc)) between 10 and 30
    group by all
)

select
    v.venue_id,
    any_value(v.venue_name)                                     as venue_name,
    any_value(v.region)                                         as region,
    any_value(v.exposure)                                       as exposure,
    any_value(v.lat)                                            as lat,
    any_value(v.lon)                                            as lon,
    any_value(v.tz)                                             as local_time_zone,
    any_value(vs.sports)                                        as sports,
    any_value(vs.n_sessions)                                    as n_sessions,
    count(*)                                                    as n_afternoons,
    round(median(a.peak_temp_c) * 9 / 5 + 32)                   as typical_afternoon_temp_f,
    round(quantile_cont(a.peak_temp_c, 0.9) * 9 / 5 + 32)       as hot_afternoon_temp_f,
    -- share of afternoons with at least 0.5 mm of rain
    avg(case when a.rain_mm >= 0.5 then 1.0 else 0.0 end)       as p_rainy_afternoon
from venues v
join afternoons a using (venue_id)
left join {{ ref('gold_venue_summary') }} vs using (venue_id)  -- sports played there, for tooltips
group by v.venue_id
