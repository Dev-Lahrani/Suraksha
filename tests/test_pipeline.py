"""Pipeline tests with mocked Open-Meteo HTTP responses (fully offline)."""

import json
from datetime import date, timedelta
from unittest.mock import patch

import httpx
import pytest

from suraksha.data import pipeline
from suraksha.db import AirQuality, RiskScore, SessionLocal, WeatherDay


def _daily_payload(days: int = 10) -> dict:
    start = date.today() - timedelta(days=7)
    times, tmax, tavg, tmin, pr, hum, wind = [], [], [], [], [], [], []
    for i in range(days):
        d = start + timedelta(days=i)
        times.append(d.isoformat())
        tmax.append(35.0 + i * 0.2)
        tavg.append(30.0 + i * 0.2)
        tmin.append(24.0)
        pr.append(50.0 if i == days - 2 else 0.5)
        hum.append(55.0)
        wind.append(10.0)
    return {
        "daily": {
            "time": times,
            "temperature_2m_max": tmax,
            "temperature_2m_mean": tavg,
            "temperature_2m_min": tmin,
            "precipitation_sum": pr,
            "relative_humidity_2m_mean": hum,
            "wind_speed_10m_max": wind,
        }
    }


def _aq_payload() -> dict:
    now = date.today()
    times = [f"{now.isoformat()}T{h:02d}:00" for h in range(24)]
    return {"hourly": {"time": times, "pm2_5": [40.0 + h for h in range(24)], "pm10": [80.0] * 24}}


class FakeClient:
    """Stands in for httpx.AsyncClient; returns canned payloads per URL."""

    def __init__(self):
        self.urls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None, timeout=None):
        self.urls.append(url)
        if "archive-api" in url:
            payload = _daily_payload(30)  # small synthetic archive is enough for tests
        elif "air-quality" in url:
            payload = _aq_payload()
        else:
            payload = _daily_payload(14)
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))


@pytest.mark.asyncio
async def test_run_pipeline_offline(clean_pune):
    with patch.object(pipeline, "httpx") as mock_httpx:
        mock_httpx.AsyncClient = FakeClient
        summary = await pipeline.run_pipeline()
    assert summary["districts"] > 30
    assert summary["weather_rows"] > 0
    assert summary["errors"] == []
    with SessionLocal() as db:
        assert db.query(WeatherDay).filter(WeatherDay.district_id == "PUNE").count() > 0
        assert db.query(RiskScore).filter(RiskScore.district_id == "PUNE").count() > 0
        assert db.query(AirQuality).filter(AirQuality.district_id == "PUNE").count() > 0


@pytest.mark.asyncio
async def test_upsert_is_idempotent(clean_pune):
    rows = [
        {"day": date.today().isoformat(), "tavg": 30.0, "tmax": 35.0, "tmin": 24.0,
         "precipitation": 10.0, "humidity": 60.0, "wind": 9.0}
    ]
    n1 = pipeline._upsert_weather("PUNE", rows)
    n2 = pipeline._upsert_weather("PUNE", rows)
    assert n1 == n2 == 1
    with SessionLocal() as db:
        assert db.query(WeatherDay).filter(WeatherDay.district_id == "PUNE").count() == 1
