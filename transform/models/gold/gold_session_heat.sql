-- Heat climatology per session: how hot does this exact slot (venue, date, hours) get
-- across ~77 analog days? Athletes see sun WBGT outdoors, shade WBGT under a roof
-- (SoFi), and a climate-controlled hall indoors (not scored for athletes).

with per_day as (
    select
        session_id,
        analog_year,
        analog_date,
        max(case exposure when 'outdoor' then wbgt_sun_c
                          when 'covered' then wbgt_shade_c end)
            filter (where not is_arrival_hour)                      as athlete_peak_wbgt_c,
        max(wbgt_sun_c) filter (where is_arrival_hour)              as arrival_wbgt_c,
        max(temp_c) filter (where not is_arrival_hour)              as peak_temp_c
    from {{ ref('slv_session_analog_hours') }}
    group by all
),

stats as (
    select
        session_id,
        count(*)                                                        as n_analog_days,
        median(athlete_peak_wbgt_c)                                     as athlete_wbgt_median_c,
        quantile_cont(athlete_peak_wbgt_c, 0.9)                         as athlete_wbgt_p90_c,
        max(athlete_peak_wbgt_c)                                        as athlete_wbgt_max_c,
        quantile_cont(arrival_wbgt_c, 0.9)                              as arrival_wbgt_p90_c,
        median(peak_temp_c)                                             as peak_temp_median_c,
        -- probability of reaching each flag on a given analog day
        avg(case when athlete_peak_wbgt_c >= 29.4 then 1.0 else 0.0 end) as p_yellow_or_worse,
        avg(case when athlete_peak_wbgt_c >= 31.1 then 1.0 else 0.0 end) as p_red_or_worse,
        avg(case when athlete_peak_wbgt_c >= 32.2 then 1.0 else 0.0 end) as p_black
    from per_day
    group by session_id
)

select
    s.*,
    f.flag      as p90_flag,
    f.flag_rank as p90_flag_rank
from stats s
left join {{ ref('wbgt_flag_thresholds') }} f
  on s.athlete_wbgt_p90_c >= f.min_wbgt_c and s.athlete_wbgt_p90_c < f.max_wbgt_c
