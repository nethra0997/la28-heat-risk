-- Summer land-surface temperature around each venue, summarised across clear scenes.
-- Landsat passes ~10:30 local time, so this is a late-morning surface picture.
select
    venue_id,
    count(*)                              as n_scenes,
    min(acquired_utc)::date               as first_scene,
    max(acquired_utc)::date               as last_scene,
    median(lst_mean_500m_c)               as lst_500m_median_c,
    median(lst_mean_2000m_c)              as lst_2km_median_c,
    median(baseline_median_c)             as lst_10km_baseline_c,
    median(lst_anomaly_500m_c)            as lst_anomaly_500m_c,
    quantile_cont(lst_mean_500m_c, 0.9)   as lst_500m_p90_c
from {{ ref('stg_landsat_lst') }}
group by venue_id
