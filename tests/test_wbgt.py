import numpy as np
import pandas as pd
import pytest

from heatrisk.wbgt import cos_zenith, wbgt, wbgt_shade


def stull_wet_bulb(t, rh):
    """Stull (2011) psychrometric wet bulb, independent check for the no-sun case."""
    return (t * np.arctan(0.151977 * (rh + 8.313659) ** 0.5) + np.arctan(t + rh)
            - np.arctan(rh - 1.676331) + 0.00391838 * rh**1.5 * np.arctan(0.023101 * rh)
            - 4.686035)


def one(**kw):
    base = dict(temp_c=[32.0], rh_pct=[40.0], pressure_hpa=[1010.0], wind_2m_ms=[2.0],
                solar_wm2=[850.0], cos_zen=[0.9], fdir=[0.8])
    base.update({k: [v] for k, v in kw.items()})
    return wbgt(**base).iloc[0]


def test_hot_sunny_afternoon_in_plausible_range():
    r = one()
    assert 45 < r.globe_temp_c < 60  # black globe in full sun runs ~15-25 C above air
    assert 27 < r.wbgt_c < 33
    # sun must push natural wet bulb above the psychrometric wet bulb (~21.9 C here)
    assert r.natural_wet_bulb_c > stull_wet_bulb(32.0, 40.0)


@pytest.mark.parametrize("t,rh", [(20, 50), (28, 70), (35, 20)])
def test_no_sun_natural_wet_bulb_close_to_psychrometric(t, rh):
    r = wbgt_shade([t], [rh], [1013.0], [3.0]).iloc[0]
    assert abs(r.natural_wet_bulb_c - stull_wet_bulb(t, rh)) < 1.0
    assert abs(r.globe_temp_c - t) < 3.0


def test_monotonic_in_sun_and_humidity():
    assert one(solar_wm2=900).wbgt_c > one(solar_wm2=300).wbgt_c > one(solar_wm2=0, cos_zen=0).wbgt_c
    assert one(rh_pct=80).wbgt_c > one(rh_pct=20).wbgt_c


def test_wind_cools_globe():
    assert one(wind_2m_ms=6).globe_temp_c < one(wind_2m_ms=0.5).globe_temp_c


def test_wbgt_below_air_temp_when_dry_and_shaded():
    assert wbgt_shade([35.0], [15.0], [1010.0], [2.0]).iloc[0].wbgt_c < 35.0


def test_vectorised_matches_scalar():
    n = 5
    df = wbgt([30] * n, [50] * n, [1010] * n, [2] * n, [800] * n, [0.8] * n)
    assert np.allclose(df.wbgt_c, df.wbgt_c.iloc[0])


def test_cos_zenith_solar_noon_la_july():
    # LA solar noon mid-July is ~20:00 UTC; zenith ~ lat - declination ~ 34 - 21.5 = 12.5 deg
    t = pd.DatetimeIndex(["2028-07-15 20:00"], tz="UTC")
    cz = cos_zenith(t, 34.05, -118.25)[0]
    assert np.degrees(np.arccos(cz)) == pytest.approx(12.8, abs=1.5)
    night = cos_zenith(pd.DatetimeIndex(["2028-07-15 10:00"], tz="UTC"), 34.05, -118.25)[0]
    assert night < 0
