"""Explainable anomaly detection vs climatology.

Every event carries the numbers that triggered it, so an advisory can cite
"3.2x the normal rainfall for this week" instead of a black-box score.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from suraksha.core.climatology import climatology_map, doy_aligned
from suraksha.db import SessionLocal, WeatherDay


def detect_anomalies(district_id: str, lookback_days: int = 7) -> list[dict]:
    """Flag statistically unusual conditions in the last `lookback_days` observations."""
    clim = climatology_map(district_id)
    with SessionLocal() as db:  # type: Session
        rows = (
            db.query(WeatherDay)
            .filter(
                WeatherDay.district_id == district_id,
                WeatherDay.is_forecast.is_(False),
            )
            .order_by(WeatherDay.day.desc())
            .limit(lookback_days)
            .all()
        )
        events: list[dict] = []
        for w in rows:
            c = clim.get(doy_aligned(w.day)) or {}
            tavg_normal = c.get("tavg_normal")
            rain_normal = c.get("rain_normal") or 0.0
            rain_p90 = c.get("rain_p90")

            # Temperature anomaly (>=5°C above normal is a heat anomaly anywhere in India)
            if w.tavg is not None and tavg_normal is not None:
                anom = w.tavg - tavg_normal
                if anom >= 5.0:
                    events.append(
                        {
                            "day": w.day.isoformat(),
                            "kind": "heat",
                            "metric": "tavg_anomaly_c",
                            "value": round(anom, 1),
                            "normal": round(tavg_normal, 1),
                            "message": (
                                f"Temperature {anom:.1f}°C above the 30-year normal "
                                f"({w.tavg:.1f}°C vs {tavg_normal:.1f}°C)"
                            ),
                        }
                    )
                elif anom <= -5.0:
                    events.append(
                        {
                            "day": w.day.isoformat(),
                            "kind": "cold",
                            "metric": "tavg_anomaly_c",
                            "value": round(anom, 1),
                            "normal": round(tavg_normal, 1),
                            "message": (
                                f"Temperature {abs(anom):.1f}°C below the 30-year normal "
                                f"({w.tavg:.1f}°C vs {tavg_normal:.1f}°C)"
                            ),
                        }
                    )

            # Extreme daily rain vs normal and vs local p90
            if w.precipitation is not None and w.precipitation >= 20:
                ratio = w.precipitation / max(rain_normal, 1.0)
                if ratio >= 3 or (rain_p90 and w.precipitation >= 2 * rain_p90):
                    events.append(
                        {
                            "day": w.day.isoformat(),
                            "kind": "extreme_rain",
                            "metric": "rain_ratio_vs_normal",
                            "value": round(ratio, 1),
                            "rain_mm": w.precipitation,
                            "normal_mm": round(rain_normal, 1),
                            "message": (
                                f"Daily rainfall {w.precipitation:.0f}mm is {ratio:.1f}x the "
                                f"30-year normal for this date ({rain_normal:.1f}mm)"
                            ),
                        }
                    )

        # Wet-spell check: 3-day accumulation >= 90th percentile 3-day climatology proxy
        if rows:
            days = [r.day for r in rows]
            newest, oldest = max(days), min(days)
            span = (newest - oldest).days + 1
            if span >= 3:
                acc = sum(r.precipitation or 0.0 for r in rows if r.precipitation is not None)
                p90_avg = _avg_p90(clim, newest, lookback_days=span)
                if p90_avg and acc >= 2.0 * p90_avg * span / 7:
                    events.append(
                        {
                            "day": newest.isoformat(),
                            "kind": "wet_spell",
                            "metric": "accumulation_mm",
                            "value": round(acc, 1),
                            "expected_mm": round(p90_avg * span / 7, 1),
                            "message": (
                                f"{span}-day rainfall total {acc:.0f}mm far exceeds the "
                                f"heavy-rain climatology (~{p90_avg * span / 7:.0f}mm)"
                            ),
                        }
                    )
        return events


def _avg_p90(clim: dict[int, dict[str, float | None]], end_day: date, lookback_days: int) -> float | None:
    vals = []
    for k in range(lookback_days):
        c = clim.get(doy_aligned(end_day - timedelta(days=k))) or {}
        if c.get("rain_p90") is not None:
            vals.append(c["rain_p90"])
    return sum(vals) / len(vals) if vals else None
