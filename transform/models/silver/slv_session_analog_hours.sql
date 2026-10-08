-- For every scorable session, find the matching hours in each baseline year:
-- same local clock hours, on the same calendar date +/- analog_window_days.
-- e.g. a 2028-07-20 11:00-14:00 session maps to 11:00-14:00 on July 17-23 of 2015..2025.
-- That gives ~7 days x 11 years = 77 "analog days" per session.

{% set w = var('analog_window_days') %}

with sessions as (
    select
        session_id, loc_id, exposure, session_date,
        timezone('America/Los_Angeles', starts_at) as start_local,
        timezone('America/Los_Angeles', ends_at)   as end_local
    from {{ ref('slv_sessions') }}
    where is_scorable
),

analog_days as (
    select
        s.*,
        y.year                                                    as analog_year,
        o.offset_days,
        cast(make_date(cast(y.year as integer), month(s.session_date), day(s.session_date))
             + to_days(cast(o.offset_days as integer)) as date)     as analog_date
    from sessions s
    cross join (select unnest(range({{ var('baseline_start_year') }},
                                    {{ var('baseline_end_year') }} + 1)) as year) y
    cross join (select unnest(range(-{{ w }}, {{ w }} + 1)) as offset_days) o
),

windows as (
    select
        *,
        analog_date + (start_local - date_trunc('day', start_local))    as analog_start,
        analog_date + (end_local - date_trunc('day', start_local))      as analog_end
    from analog_days
)

select
    w.session_id,
    w.exposure,
    w.analog_year,
    w.analog_date,
    h.time_local,
    h.temp_c,
    h.rh_pct,
    h.wbgt_sun_c,
    h.wbgt_shade_c,
    h.ghi_wm2,
    h.precip_mm,
    -- Hour the spectators arrive: the hour before the session starts
    (h.time_local < w.analog_start)                                    as is_arrival_hour
from windows w
join {{ ref('slv_weather_wbgt') }} h
  on h.loc_id = w.loc_id
 and h.time_local >= w.analog_start - interval 1 hour
 and h.time_local <= w.analog_end
