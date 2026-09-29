select
    venue_label,
    venue_id,
    venue_name,
    exposure,        -- outdoor | covered | indoor
    region,          -- la_metro | socal | remote
    notes,
    lat,
    lon,
    round(lat, 3)::varchar || '_' || round(lon, 3)::varchar as loc_id,
    geocode_source,
    osm_display_name
from {{ source('bronze', 'venues') }}
