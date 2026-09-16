"""Anomaly detection tests (uses the seeded test DB, PUNE district)."""

from datetime import date, timedelta

from suraksha.core.anomaly import detect_anomalies
from suraksha.core.climatology import compute_climatology
from suraksha.db import SessionLocal, WeatherDay
import pandas as pd


def _seed_climatology():
    """Synthetic Pune-like climatology: mild temps, moderate monsoon rain."""
    rows = []
    start = date(2024, 1, 1)
    for i in range(365 * 30):
        d = start + timedelta(days=i)
        doy = d.timetuple().tm_yday
        rows.append(
            {
                "day": d.isoformat(),
                "tavg": 26.0,  # flat all-year normal
                "precipitation": 2.0 if 150 < doy < 270 else 0.1,
            }
        )
    df = pd.DataFrame(rows)
    compute_climatology("PUNE", df)


def test_no_anomalies_on_normal_weather(clean_pune):
    _seed_climatology()
    today = date.today()
    with SessionLocal() as db:
        for k in range(5):
            day = today - timedelta(days=k)
            db.add(
                WeatherDay(
                    district_id="PUNE",
                    day=day,
                    tavg=26.0,  # exactly normal
                    tmax=31.0,
                    tmin=21.0,
                    precipitation=0.2,  # well below monsoon p90 (2mm) — no wet spell
                    humidity=60,
                    wind=8,
                    is_forecast=False,
                )
            )
        db.commit()
    assert detect_anomalies("PUNE", lookback_days=7) == []


def test_heat_and_extreme_rain_detected(clean_pune):
    _seed_climatology()
    today = date.today()
    with SessionLocal() as db:
        db.add(
            WeatherDay(
                district_id="PUNE",
                day=today - timedelta(days=1),
                tavg=34.0,  # +8°C vs normal 26
                tmax=40.0,
                tmin=28.0,
                precipitation=80.0,  # way above ~2mm normal
                humidity=55,
                wind=10,
                is_forecast=False,
            )
        )
        db.commit()
    events = detect_anomalies("PUNE", lookback_days=7)
    kinds = {e["kind"] for e in events}
    assert "heat" in kinds
    assert "extreme_rain" in kinds
    heat = next(e for e in events if e["kind"] == "heat")
    assert heat["value"] == 8.0
    assert heat["message"].startswith("Temperature 8.0°C above")


def test_wet_spell_detected(clean_pune):
    _seed_climatology()
    today = date.today()
    with SessionLocal() as db:
        for k in range(1, 6):
            db.add(
                WeatherDay(
                    district_id="PUNE",
                    day=today - timedelta(days=k),
                    tavg=26.0,
                    tmax=30.0,
                    tmin=22.0,
                    precipitation=60.0,
                    humidity=85,
                    wind=12,
                    is_forecast=False,
                )
            )
        db.commit()
    events = detect_anomalies("PUNE", lookback_days=7)
    assert any(e["kind"] == "wet_spell" for e in events)
