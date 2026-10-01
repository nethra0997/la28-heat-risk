-- A one-off ("singular") test: every place should have exactly one row per hour.
-- Returns any (loc_id, time_utc) pair that appears more than once; zero rows = pass.
select loc_id, time_utc, count(*) as n
from {{ ref('slv_weather_wbgt') }}
group by loc_id, time_utc
having count(*) > 1
