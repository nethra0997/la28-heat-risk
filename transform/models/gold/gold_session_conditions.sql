-- A fan's guide to each session: what it is likely to feel like to be there, and what to bring.
-- Built from the same ~77 analog days per session as gold_session_heat, in plain terms:
-- temperatures in °F, a comfort level, chance of rain, sun and smog. Advice comes from fixed,
-- documented rules (below), not from a model, so it is consistent and checkable.

with per_day as (
    -- one row per session per analog day, over the session's own hours
    select
        session_id,
        analog_year,
        analog_date,
        max(temp_c)    filter (where not is_arrival_hour) as peak_temp_c,
        min(temp_c)    filter (where not is_arrival_hour) as low_temp_c,
        sum(precip_mm) filter (where not is_arrival_hour) as rain_mm,
        avg(ghi_wm2)   filter (where not is_arrival_hour) as mean_sun_wm2
    from {{ ref('slv_session_analog_hours') }}
    group by all
),

stats as (
    select
        session_id,
        median(peak_temp_c)                                  as typical_temp_c,
        quantile_cont(peak_temp_c, 0.9)                      as hot_day_temp_c,
        median(low_temp_c)                                   as typical_low_temp_c,
        -- share of analog days with at least 0.5 mm of rain during the session
        avg(case when rain_mm >= 0.5 then 1.0 else 0.0 end)  as p_rain,
        median(mean_sun_wm2)                                 as typical_sun_wm2
    from per_day
    group by session_id
),

classified as (
    select
        s.session_id,
        s.sport,
        s.venue_id,
        s.venue_name,
        s.zone,
        s.region,
        s.exposure,
        s.session_date,
        s.start_time,
        s.end_time,
        s.medal,
        s.is_scorable,
        case
            when s.starts_at is null then null
            when hour(timezone('America/Los_Angeles', s.starts_at)) < 12 then 'Morning'
            when hour(timezone('America/Los_Angeles', s.starts_at)) < 17 then 'Afternoon'
            else 'Evening'
        end                                                  as time_of_day,
        st.typical_temp_c,
        st.hot_day_temp_c,
        st.typical_low_temp_c,
        st.p_rain,
        st.typical_sun_wm2,
        h.athlete_wbgt_p90_c,
        h.p_yellow_or_worse,
        aq.share_days_ozone_aqi_gt_100,
        -- Comfort level from heat stress on a bad day (WBGT p90), using the US Army flag bands.
        case
            when not s.is_scorable or st.session_id is null then 'Not yet scheduled'
            when s.exposure = 'indoor'                      then 'Indoors'
            when h.athlete_wbgt_p90_c >= 31.1               then 'Very hot'
            when h.athlete_wbgt_p90_c >= 29.4               then 'Hot'
            when h.athlete_wbgt_p90_c >= 26.7               then 'Warm'
            else 'Comfortable'
        end                                                  as comfort
    from {{ ref('slv_sessions') }} s
    left join stats st using (session_id)
    left join {{ ref('gold_session_heat') }} h using (session_id)
    left join {{ ref('slv_venue_air_quality') }} aq using (venue_id)
)

select
    session_id,
    sport,
    venue_id,
    venue_name,
    zone,
    region,
    exposure,
    session_date,
    start_time,
    end_time,
    medal,
    time_of_day,
    comfort,
    case comfort
        when 'Comfortable' then 1 when 'Warm' then 2 when 'Hot' then 3 when 'Very hot' then 4
        when 'Indoors' then 0 end                                       as comfort_rank,
    round(typical_temp_c * 9 / 5 + 32)                                   as typical_temp_f,
    round(hot_day_temp_c * 9 / 5 + 32)                                   as hot_day_temp_f,
    round(typical_low_temp_c * 9 / 5 + 32)                               as typical_low_temp_f,
    p_rain,
    p_yellow_or_worse                                                    as p_heat_flag,
    share_days_ozone_aqi_gt_100                                          as p_smoggy_day,
    (exposure = 'outdoor' and typical_sun_wm2 >= 500)                    as strong_sun,
    -- What to bring: each rule adds a phrase; concat_ws skips the rules that don't apply.
    case when comfort = 'Not yet scheduled' then null else concat_ws('; ',
        case when exposure = 'outdoor' and typical_sun_wm2 >= 500 then 'sunscreen and a hat' end,
        case when comfort in ('Warm', 'Hot', 'Very hot') then 'plenty of water'
             when comfort = 'Indoors' then 'water for the queue outside' end,
        case when comfort in ('Hot', 'Very hot') then 'plan breaks in the shade' end,
        case when p_rain >= 0.15 then 'a rain layer' end,
        case when exposure <> 'indoor' and typical_low_temp_c < 18 then 'a light layer for when it cools' end,
        case when exposure <> 'indoor' and share_days_ozone_aqi_gt_100 >= 0.10
             then 'check air quality if you are sensitive to smog' end
    ) end                                                                as what_to_bring
from classified
