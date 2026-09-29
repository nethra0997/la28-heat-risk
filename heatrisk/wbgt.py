"""Outdoor Wet Bulb Globe Temperature from standard meteorological data.

Implements the Liljegren et al. (2008) model -- "Modeling the Wet Bulb Globe
Temperature Using Standard Meteorological Measurements", J. Occup. Environ. Hyg.
5(10):645-655 -- the method behind OSHA/NWS WBGT tools. It solves the energy
balance of a 2-inch black globe (Tg) and a wetted wick (natural wet bulb, Tnwb)
by fixed-point iteration, then

    WBGT = 0.7 * Tnwb + 0.2 * Tg + 0.1 * Ta

Vectorised with numpy so a whole hourly weather table is processed at once.
Units in the public API: degC, %, hPa, m/s, W/m2.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Physical constants (Liljegren 2008, Table I and reference implementation)
STEFANB = 5.6696e-8
CP = 1003.5  # J/(kg K), specific heat of dry air
M_AIR, M_H2O = 28.97, 18.015
R_GAS = 8314.34
R_AIR = R_GAS / M_AIR
PR = CP / (CP + 1.25 * R_AIR)  # Prandtl number
RATIO = CP * M_AIR / M_H2O

EMIS_GLOBE, ALB_GLOBE, D_GLOBE = 0.95, 0.05, 0.0508
EMIS_WICK, ALB_WICK, D_WICK, L_WICK = 0.95, 0.4, 0.007, 0.0254
EMIS_SFC, ALB_SFC = 0.999, 0.45

MIN_SPEED = 0.13  # m/s; still air still has free convection
CZA_MIN = 0.00873  # cos(89.5 deg): below this treat the sun as set
CONVERGENCE, MAX_ITER = 0.02, 50
SOLAR_CONST = 1367.0


# --- thermophysical properties of air (T in K, P in hPa) --------------------
def esat(t_k, p_hpa):
    """Saturation vapour pressure over water (hPa), Buck (1981) with enhancement."""
    t_c = t_k - 273.15
    return 6.1121 * np.exp(17.502 * t_c / (t_k - 32.18)) * (1.0007 + 3.46e-6 * p_hpa)


def viscosity(t_k):
    omega = (t_k / 97.0 - 2.9) / 0.4 * (-0.034) + 1.048
    return 0.0000026693 * np.sqrt(28.97 * t_k) / (3.617**2 * omega)


def thermal_cond(t_k):
    return (CP + 1.25 * R_AIR) * viscosity(t_k)


def diffusivity(t_k, p_hpa):
    pcrit13 = (36.4 * 218.0) ** (1.0 / 3.0)
    tcrit512 = (132.0 * 647.3) ** (5.0 / 12.0)
    tcrit12 = np.sqrt(132.0 * 647.3)
    mmix = np.sqrt(1.0 / 28.97 + 1.0 / 18.015)
    return (0.000364 * (t_k / tcrit12) ** 2.334 * pcrit13 * tcrit512 * mmix
            / (p_hpa / 1013.25) * 0.0001)


def evap_heat(t_k):
    return (313.15 - t_k) / 30.0 * (-71100.0) + 2.4073e6


def emis_atm(t_k, rh_frac, p_hpa):
    e = rh_frac * esat(t_k, p_hpa)
    return 0.575 * e**0.143


def h_sphere(t_k, p_hpa, speed, diameter):
    density = p_hpa * 100.0 / (R_AIR * t_k)
    re = np.maximum(speed, MIN_SPEED) * density * diameter / viscosity(t_k)
    nu = 2.0 + 0.6 * np.sqrt(re) * PR**0.3333
    return nu * thermal_cond(t_k) / diameter


def h_cylinder(t_k, p_hpa, speed, diameter):
    density = p_hpa * 100.0 / (R_AIR * t_k)
    re = np.maximum(speed, MIN_SPEED) * density * diameter / viscosity(t_k)
    nu = 0.281 * re ** (1.0 - 0.4) * PR ** (1.0 - 0.56)
    return nu * thermal_cond(t_k) / diameter


# --- solar geometry ----------------------------------------------------------
def cos_zenith(times_utc: pd.DatetimeIndex | pd.Series, lat, lon) -> np.ndarray:
    """Cosine of the solar zenith angle (NOAA general solar position equations)."""
    t = pd.DatetimeIndex(times_utc)
    if t.tz is None:
        t = t.tz_localize("UTC")
    t = t.tz_convert("UTC")
    doy = t.dayofyear.to_numpy()
    hour = (t.hour + t.minute / 60.0 + t.second / 3600.0).to_numpy()
    g = 2 * np.pi / 365.0 * (doy - 1 + (hour - 12) / 24.0)
    eqtime = 229.18 * (0.000075 + 0.001868 * np.cos(g) - 0.032077 * np.sin(g)
                       - 0.014615 * np.cos(2 * g) - 0.040849 * np.sin(2 * g))
    decl = (0.006918 - 0.399912 * np.cos(g) + 0.070257 * np.sin(g) - 0.006758 * np.cos(2 * g)
            + 0.000907 * np.sin(2 * g) - 0.002697 * np.cos(3 * g) + 0.00148 * np.sin(3 * g))
    tst = hour * 60 + eqtime + 4 * np.asarray(lon)  # true solar time, minutes
    ha = np.radians(tst / 4 - 180)
    latr = np.radians(np.asarray(lat))
    return np.sin(latr) * np.sin(decl) + np.cos(latr) * np.cos(decl) * np.cos(ha)


def direct_fraction_estimate(solar, cza):
    """Liljegren's empirical direct-beam fraction, used when no split is observed."""
    toa = SOLAR_CONST * np.maximum(cza, 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        norm = np.where(toa > 0, np.minimum(solar / toa, 0.85), 0)
        fdir = np.where(norm > 0, np.exp(3 - 1.34 * norm - 1.65 / norm), 0)
    return np.clip(fdir, 0, 0.9)


def wind_at_2m(speed_10m, exponent: float = 0.15):
    """Power-law adjustment from 10 m to 2 m (neutral stability, open terrain)."""
    return np.asarray(speed_10m) * (2.0 / 10.0) ** exponent


# --- core model ---------------------------------------------------------------
def _globe_temp(ta_k, rh, p, speed, solar, fdir, cza):
    tsfc = ta_k
    tg = ta_k.copy()
    eatm = emis_atm(ta_k, rh, p)
    beam_geom = np.where(cza > CZA_MIN, fdir * (1.0 / (2.0 * np.maximum(cza, CZA_MIN)) - 1.0), 0)
    for _ in range(MAX_ITER):
        tref = 0.5 * (tg + ta_k)
        h = h_sphere(tref, p, speed, D_GLOBE)
        new = (0.5 * (eatm * ta_k**4 + EMIS_SFC * tsfc**4)
               - h / (EMIS_GLOBE * STEFANB) * (tg - ta_k)
               + solar / (2 * EMIS_GLOBE * STEFANB) * (1 - ALB_GLOBE)
               * (beam_geom + 1 + ALB_SFC)) ** 0.25
        done = np.abs(new - tg) < CONVERGENCE
        tg = np.where(done, new, 0.9 * tg + 0.1 * new)
        if done.all():
            break
    return tg


def _natural_wet_bulb(ta_k, rh, p, speed, solar, fdir, cza):
    tsfc = ta_k
    eair = rh * esat(ta_k, p)
    eatm = emis_atm(ta_k, rh, p)
    # start from the dew point
    x = np.log(np.maximum(eair, 1e-6) / (6.1121 * (1.0007 + 3.46e-6 * p)))
    tdew_c = 240.97 * x / (17.502 - x)
    twb = tdew_c + 273.15
    zenith = np.arccos(np.clip(cza, -1, 1))
    tan_z = np.where(cza > CZA_MIN, np.tan(zenith), 0)
    solar_term = (1 - ALB_WICK) * solar * (
        (1 - fdir) * (1 + 0.25 * D_WICK / L_WICK)
        + fdir * (tan_z / np.pi + 0.25 * D_WICK / L_WICK)
        + ALB_SFC)
    for _ in range(MAX_ITER):
        tref = 0.5 * (twb + ta_k)
        h = h_cylinder(tref, p, speed, D_WICK)
        fatm = STEFANB * EMIS_WICK * (0.5 * (eatm * ta_k**4 + EMIS_SFC * tsfc**4) - twb**4) + solar_term
        ewick = esat(twb, p)
        density = p * 100.0 / (R_AIR * tref)
        sc = viscosity(tref) / (density * diffusivity(tref, p))
        new = (ta_k - evap_heat(tref) / RATIO * (ewick - eair) / (p - ewick) * (PR / sc) ** 0.56
               + fatm / h)
        done = np.abs(new - twb) < CONVERGENCE
        twb = np.where(done, new, 0.9 * twb + 0.1 * new)
        if done.all():
            break
    return twb


def wbgt(temp_c, rh_pct, pressure_hpa, wind_2m_ms, solar_wm2, cos_zen, fdir=None) -> pd.DataFrame:
    """Return Tg, Tnwb and WBGT (degC) for arrays of hourly inputs.

    fdir: fraction of solar that is direct beam. If None, estimated (Liljegren).
    """
    ta = np.asarray(temp_c, dtype=float) + 273.15
    rh = np.clip(np.asarray(rh_pct, dtype=float), 1, 100) / 100.0
    p = np.asarray(pressure_hpa, dtype=float)
    u = np.maximum(np.asarray(wind_2m_ms, dtype=float), MIN_SPEED)
    cza = np.asarray(cos_zen, dtype=float)
    solar = np.where(cza > CZA_MIN, np.maximum(np.asarray(solar_wm2, dtype=float), 0), 0)
    if fdir is None:
        fd = direct_fraction_estimate(solar, cza)
    else:
        fd = np.clip(np.nan_to_num(np.asarray(fdir, dtype=float)), 0, 1)
    fd = np.where(cza > CZA_MIN, fd, 0)

    tg = _globe_temp(ta, rh, p, u, solar, fd, cza) - 273.15
    tnwb = _natural_wet_bulb(ta, rh, p, u, solar, fd, cza) - 273.15
    ta_c = ta - 273.15
    return pd.DataFrame({
        "globe_temp_c": tg,
        "natural_wet_bulb_c": tnwb,
        "wbgt_c": 0.7 * tnwb + 0.2 * tg + 0.1 * ta_c,
    })


def wbgt_shade(temp_c, rh_pct, pressure_hpa, wind_2m_ms):
    """WBGT with no solar load (shade / night)."""
    n = np.size(temp_c)
    return wbgt(temp_c, rh_pct, pressure_hpa, wind_2m_ms, np.zeros(n), np.zeros(n))
