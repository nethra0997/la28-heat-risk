-- July-August air quality near each venue. For each day use the nearest reporting monitor.
with ranked as (
    select
        *,
        row_number() over (partition by venue_id, pollutant, obs_date order by distance_km) as rn
    from {{ ref('stg_aq_daily') }}
),

daily as (
    select * from ranked where rn = 1
)

select
    venue_id,
    count(distinct obs_date) filter (where pollutant = 'ozone')                         as ozone_days,
    avg(aqi) filter (where pollutant = 'ozone')                                          as ozone_aqi_mean,
    quantile_cont(aqi, 0.9) filter (where pollutant = 'ozone')                            as ozone_aqi_p90,
    avg(case when aqi > 100 then 1.0 else 0.0 end) filter (where pollutant = 'ozone')    as share_days_ozone_aqi_gt_100,
    avg(daily_mean) filter (where pollutant = 'pm25')                                     as pm25_mean_ugm3,
    min(distance_km) filter (where pollutant = 'ozone')                                   as nearest_ozone_monitor_km
from daily
group by venue_id
