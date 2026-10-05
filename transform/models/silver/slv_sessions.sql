-- Scheduled sessions with venue attributes. Sessions without a known location
-- (race walk "TBD") or time (soccer group stage "TBD") are kept but flagged.
select
    s.session_id,
    s.zone,
    s.sport,
    s.session_date,
    s.day_number,
    s.start_time,
    s.end_time,
    s.starts_at,
    s.ends_at,
    s.status,
    s.medal,
    s.schedule_version,
    v.venue_id,
    coalesce(v.venue_name, s.venue_label)          as venue_name,
    v.exposure,
    v.region,
    v.loc_id,
    v.lat,
    v.lon,
    (v.venue_id is not null and s.starts_at is not null) as is_scorable
from {{ ref('stg_schedule_sessions') }} s
left join {{ ref('stg_venues') }} v using (venue_label)
where s.status = 'scheduled' or s.status = 'tbd'
