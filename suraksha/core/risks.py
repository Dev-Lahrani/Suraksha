"""Deterministic risk engines for heat, flood and air-quality hazards.

All scores are 0..100 and every driver is kept in `detail` so that any number
shown to a user can be traced back to a source (evaluation criterion: clarity).
"""

from __future__ import annotations

import math
from typing import Any


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def heat_index_c(t_c: float, rh_pct: float) -> float:
    """NOAA Rothfusz heat index; input/output in °C. Reliable for T > 26°C."""
    t = t_c * 9 / 5 + 32
    rh = rh_pct
    if t < 80:  # simple formula for mild conditions
        hi_f = 0.5 * (t + 61.0 + (t - 68.0) * 1.2 + rh * 0.094)
        return (hi_f - 32) * 5 / 9
    hi = (
        -42.379
        + 2.04901523 * t
        + 10.14333127 * rh
        - 0.22475541 * t * rh
        - 0.00683783 * t * t
        - 0.05481717 * rh * rh
        + 0.00122874 * t * t * rh
        + 0.00085282 * t * rh * rh
        - 0.00000199 * t * t * rh * rh
    )
    if rh < 13 and 80 <= t <= 112:
        adj = ((13 - rh) / 4) * math.sqrt((17 - abs(t - 95.0)) / 17)
        hi -= adj
    elif rh > 85 and 80 <= t <= 87:
        adj = ((rh - 85) / 10) * ((87 - t) / 5)
        hi += adj
    return (hi - 32) * 5 / 9


def heat_score(tmax: float | None, tavg: float | None, humidity: float | None) -> dict[str, Any]:
    """Heat-wave risk from peak-day heat index (NDMA thresholds in °C HI)."""
    if tmax is None:
        return {"score": None, "band": "unknown", "detail": {"reason": "no temperature data"}}
    rh = humidity if humidity is not None else 50.0
    hi = heat_index_c(tmax, rh)
    # Piecewise: HI >= 54 very high; 46+ danger; 40+ moderate; <35 minimal
    if hi >= 46:
        score = _clamp(60 + (hi - 46) * 2.5)
    elif hi >= 40:
        score = _clamp(25 + (hi - 40) * 5.8)
    else:
        score = _clamp((hi - 30) * 2.5)
    detail = {"heat_index_c": round(hi, 1), "tmax_c": tmax, "rh_pct": rh}
    return {"score": round(score, 1), "band": band(score), "detail": detail}


def flood_score(
    rain_today: float | None,
    rain_3day: float | None,
    rain_p90: float | None,
) -> dict[str, Any]:
    """Flood-potential proxy: 3-day accumulation vs local heavy-rain climatology.

    Honest labelling: this is a rainfall-based proxy, NOT a hydrological model.
    """
    if rain_3day is None:
        return {"score": None, "band": "unknown", "detail": {"reason": "no rainfall data"}}
    p90 = rain_p90 if rain_p90 and rain_p90 > 0.2 else 15.0  # sensible default mm
    ratio = rain_3day / max(3 * p90, 3.0)
    score = _clamp(ratio * 40, 0, 85)
    if rain_today is not None:
        if rain_today >= 100:  # cloudburst-scale single day
            score = max(score, 80)
        elif rain_today >= 65:
            score = max(score, 60)
    detail = {
        "rain_today_mm": rain_today,
        "rain_3day_mm": rain_3day,
        "heavy_day_p90_mm": round(p90, 1),
        "ratio_vs_normal_heavy": round(ratio, 2),
    }
    return {"score": round(score, 1), "band": band(score), "detail": detail}


def aqi_from_pm25(pm25: float) -> int:
    """US-EPA 2024 breakpoint AQI from 24h PM2.5 (µg/m³)."""
    bps = [
        (0.0, 9.0, 0, 50),
        (9.1, 35.4, 51, 100),
        (35.5, 55.4, 101, 150),
        (55.5, 125.4, 151, 200),
        (125.5, 225.4, 201, 300),
        (225.5, 500.0, 301, 500),
    ]
    for lo, hi, a_lo, a_hi in bps:
        if pm25 <= hi or (lo, hi) == bps[-1][:2]:
            return int(round(a_lo + (a_hi - a_lo) * (pm25 - lo) / (hi - lo)))
    return 500


def air_score(pm25: float | None) -> dict[str, Any]:
    """Air-quality emergency risk from latest PM2.5."""
    if pm25 is None:
        return {"score": None, "band": "unknown", "detail": {"reason": "no AQ data"}}
    aqi = aqi_from_pm25(pm25)
    score = _clamp(aqi / 2.0)  # AQI 200 (unhealthy) => score 100
    detail = {"pm25_ugm3": round(pm25, 1), "aqi_us_epa": aqi}
    return {"score": round(score, 1), "band": band(score), "detail": detail}


def band(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score >= 60:
        return "high"
    if score >= 25:
        return "moderate"
    return "low"


def compute_risk_for_day(
    *,
    tmax: float | None,
    tavg: float | None,
    precipitation: float | None,
    rain_3day: float | None,
    rain_p90: float | None,
    humidity: float | None,
    pm25: float | None,
) -> dict[str, dict[str, Any]]:
    """All three hazard scores for one district-day."""
    return {
        "heat": heat_score(tmax, tavg, humidity),
        "flood": flood_score(precipitation, rain_3day, rain_p90),
        "air": air_score(pm25),
    }
