select
    venue_id,
    scene_id,
    cast(acquired_utc as timestamptz) as acquired_utc,
    platform,
    scene_cloud_cover,
    valid_fraction,
    lst_mean_500m_c,
    lst_mean_2000m_c,
    baseline_median_c,
    lst_anomaly_500m_c
from {{ source('bronze', 'landsat_lst') }}
-- guard against partially-covered or mis-masked scenes
where valid_fraction >= 0.7
  and lst_mean_500m_c between 0 and 80
