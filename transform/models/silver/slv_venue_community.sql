-- Population-and-area weighted vulnerability of the neighbourhood (3 km) around each venue.
-- Weight = tract population x share of the tract inside the buffer, so a sliver of a
-- big tract counts less than a tract fully inside.
with j as (
    select
        vt.venue_id,
        t.*,
        coalesce(t.pop_total, 0) * least(vt.overlap_share_of_tract, 1.0) as w
    from {{ source('bronze', 'venue_tracts') }} vt
    join {{ ref('stg_tract_vulnerability') }} t using (geoid)
)

select
    venue_id,
    count(*)                                                         as n_tracts,
    round(sum(w))                                                    as est_population_3km,
    sum(svi_overall_pctile * w) / nullif(sum(w) filter (where svi_overall_pctile is not null), 0)
                                                                     as svi_overall_pctile,
    sum(share_65_plus * w) / nullif(sum(w) filter (where share_65_plus is not null), 0)
                                                                     as share_65_plus,
    sum(share_hh_no_vehicle * w) / nullif(sum(w) filter (where share_hh_no_vehicle is not null), 0)
                                                                     as share_hh_no_vehicle,
    sum(share_poverty * w) / nullif(sum(w) filter (where share_poverty is not null), 0)
                                                                     as share_poverty,
    max(svi_overall_pctile)                                          as svi_max_tract_pctile
from j
group by venue_id
