-- NWS hourly forecast. Temperature comes in F; wind as text like "5 to 10 mph".
select
    loc_id,
    cast(start_time as timestamptz)                                        as time_utc,
    is_daytime,
    case when temperature_unit = 'F' then (temperature - 32) * 5 / 9.0
         else temperature end                                              as temp_c,
    dewpoint_c,
    relative_humidity_pct                                                  as rh_pct,
    -- take the upper bound of "5 to 10 mph" -> m/s
    cast(regexp_extract(wind_speed_text, '(\d+)\s*mph', 1) as double) * 0.44704 as wind_10m_ms,
    short_forecast,
    precip_probability_pct,
    issued_at
from {{ source('bronze', 'nws_forecast_hourly') }}
