-- EPA AirData daily summaries. Ozone rows are daily max 8-hour averages (ppm);
-- one monitor can report several rows per day (different sampling durations) -> keep max.
select
    venue_id,
    pollutant,
    lpad(cast(state_code as varchar), 2, '0') || lpad(cast(county_code as varchar), 3, '0')
        || lpad(cast(site_num as varchar), 4, '0')          as monitor_id,
    cast(date_local as date)                                as obs_date,
    distance_km,
    max(arithmetic_mean)                                    as daily_mean,
    max("1st_max_value")                                    as daily_max,
    max(aqi)                                                as aqi
from {{ source('bronze', 'aq_daily_history') }}
group by all
