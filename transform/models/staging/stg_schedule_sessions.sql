-- One row per competition session. Times in the PDF are Pacific (America/Los_Angeles).
with src as (
    select * from {{ source('bronze', 'schedule_sessions') }}
)

select
    md5(concat_ws('|', venue_label, sport, session_date, coalesce(start_time, ''),
                  row_number() over (partition by venue_label, sport, session_date, start_time
                                     order by page)))          as session_id,
    zone,
    venue_label,
    sport,
    cast(session_date as date)                                 as session_date,
    day_number,
    start_time,
    end_time,
    ends_next_day,
    status,
    medal,
    schedule_version,
    -- local wall-clock -> timestamptz
    case when start_time is not null then
        timezone('America/Los_Angeles', cast(session_date as date) + cast(start_time as time))
    end                                                        as starts_at,
    case when end_time is not null then
        timezone('America/Los_Angeles',
                 cast(session_date as date) + cast(end_time as time)
                 + case when ends_next_day then interval 1 day else interval 0 day end)
    end                                                        as ends_at
from src
