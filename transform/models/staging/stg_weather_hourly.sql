-- Open-Meteo archive. Radiation fields are the mean over the hour *ending* at time_utc;
-- state variables (temperature, humidity, wind) are instantaneous at time_utc.
select
    w.loc_id,
    l.lat,
    l.lon,
    w.time_utc,
    timezone('America/Los_Angeles', w.time_utc)   as time_local,
    year(timezone('America/Los_Angeles', w.time_utc)) as year_local,
    w.temperature_2m            as temp_c,
    w.relative_humidity_2m      as rh_pct,
    w.dew_point_2m              as dewpoint_c,
    w.surface_pressure          as pressure_hpa,
    w.wind_speed_10m            as wind_10m_ms,
    w.cloud_cover               as cloud_cover_pct,
    w.shortwave_radiation       as ghi_wm2,
    w.direct_radiation          as direct_wm2,
    w.diffuse_radiation         as diffuse_wm2,
    w.precipitation             as precip_mm,
    w.grid_elevation_m
from {{ source('bronze', 'weather_hourly_history') }} w
join {{ source('bronze', 'weather_locations') }} l using (loc_id)
where w.temperature_2m is not null
