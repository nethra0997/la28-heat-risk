-- Daily forecast peak WBGT per venue for the next ~7 days, compared to the venue's
-- own late-July baseline. Useful now as a live demo, essential during Games time.
with daily as (
    select
        f.loc_id,
        timezone('America/Los_Angeles', f.time_utc)::date  as forecast_date,
        max(f.wbgt_sun_c)                                  as peak_wbgt_sun_c,
        max(f.temp_c)                                      as peak_temp_c,
        arg_max(f.short_forecast, f.wbgt_sun_c)            as conditions_at_peak,
        any_value(f.issued_at)                             as issued_at
    from {{ ref('slv_forecast_wbgt') }} f
    group by all
),

baseline as (
    select loc_id, quantile_cont(daily_peak, 0.9) as baseline_p90_peak_wbgt_c
    from (
        select loc_id, time_local::date as d, max(wbgt_sun_c) as daily_peak
        from {{ ref('slv_weather_wbgt') }}
        where month(time_local) = 7
        group by all
    )
    group by loc_id
)

select
    v.venue_id,
    v.venue_name,
    v.exposure,
    d.forecast_date,
    d.peak_wbgt_sun_c,
    d.peak_temp_c,
    d.conditions_at_peak,
    b.baseline_p90_peak_wbgt_c,
    f.flag                                            as forecast_flag,
    d.issued_at
from daily d
join (select distinct venue_id, venue_name, exposure, loc_id from {{ ref('stg_venues') }}) v using (loc_id)
left join baseline b using (loc_id)
left join {{ ref('wbgt_flag_thresholds') }} f
  on d.peak_wbgt_sun_c >= f.min_wbgt_c and d.peak_wbgt_sun_c < f.max_wbgt_c
