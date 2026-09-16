"""Async Open-Meteo clients (no API key required).

Endpoints used:
- forecast:    https://api.open-meteo.com/v1/forecast
- archive:     https://archive-api.open-meteo.com/v1/archive  (ERA5)
- air-quality: https://air-quality-api.open-meteo.com/v1/air-quality (CAMS PM2.5)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date

import httpx

logger = logging.getLogger(__name__)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

DAILY_VARS = (
    "temperature_2m_max,temperature_2m_min,temperature_2m_mean,"
    "precipitation_sum,relative_humidity_2m_mean,wind_speed_10m_max"
)


async def _get_json(client: httpx.AsyncClient, url: str, params: dict) -> dict:
    """GET with retries: patient exponential backoff, 429-aware (Retry-After)."""
    last_err: Exception | None = None
    waits = [2, 5, 15, 30, 60]
    for attempt, wait in enumerate(waits, start=1):
        try:
            resp = await client.get(url, params=params, timeout=60.0)
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                wait = float(retry_after) if retry_after else wait
                raise _RateLimited(url)
            resp.raise_for_status()
            return resp.json()
        except _RateLimited as exc:
            last_err = exc
            logger.warning("rate limited on %s (attempt %d); sleeping %.0fs", url, attempt, wait)
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            logger.warning("GET %s failed (attempt %d): %s", url, attempt + 1, exc)
            wait = waits[min(attempt, len(waits) - 1)]
        if attempt < len(waits):
            await asyncio.sleep(wait)
    raise RuntimeError(f"Open-Meteo request failed after retries: {url} ({last_err})")


class _RateLimited(Exception):
    pass


_archive_lock: asyncio.Lock | None = None


def _get_archive_lock() -> asyncio.Lock:
    global _archive_lock
    if _archive_lock is None:
        _archive_lock = asyncio.Lock()
    return _archive_lock


async def fetch_forecast(
    client: httpx.AsyncClient, lat: float, lon: float, days: int = 7, past_days: int = 7
) -> dict:
    """Daily observed (past_days) + forecast weather, IST timezone."""
    data = await _get_json(
        client,
        FORECAST_URL,
        {
            "latitude": lat,
            "longitude": lon,
            "daily": DAILY_VARS,
            "past_days": past_days,
            "forecast_days": days,
            "timezone": "Asia/Kolkata",
        },
    )
    return _parse_daily(data)


async def fetch_archive(
    client: httpx.AsyncClient, lat: float, lon: float, start: date, end: date
) -> dict:
    """Reanalysis archive daily means (used for climatology + ML training).

    30-year requests are heavy: serialized with a small gap to stay under the
    public rate limit (a real lesson from the first live run — see decision.md D10).
    """
    lock = _get_archive_lock()
    async with lock:
        await asyncio.sleep(1.0)  # space out the heavy multi-decade requests
        data = await _get_json(
            client,
            ARCHIVE_URL,
            {
                "latitude": lat,
                "longitude": lon,
                "daily": DAILY_VARS,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "timezone": "Asia/Kolkata",
            },
        )
    return _parse_daily(data)


async def fetch_pm25(
    client: httpx.AsyncClient, lat: float, lon: float, past_days: int = 2
) -> list[dict]:
    """Hourly PM2.5/PM10 for the past days; returns [{hour, pm25, pm10}]."""
    data = await _get_json(
        client,
        AQ_URL,
        {
            "latitude": lat,
            "longitude": lon,
            "hourly": "pm2_5,pm10",
            "past_days": past_days,
            "forecast_days": 1,
            "timezone": "Asia/Kolkata",
        },
    )
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    pm25 = hourly.get("pm2_5", [])
    pm10 = hourly.get("pm10", [])
    out = []
    for i, t in enumerate(times):
        p25 = pm25[i] if i < len(pm25) else None
        p10 = pm10[i] if i < len(pm10) else None
        out.append({"hour": t, "pm25": p25, "pm10": p10})
    return out


def _parse_daily(data: dict) -> dict:
    daily = data.get("daily", {})
    times = daily.get("time", [])
    out: list[dict] = []
    for i, d in enumerate(times):
        def _v(key: str) -> float | None:
            vals = daily.get(key, [])
            v = vals[i] if i < len(vals) else None
            return float(v) if v is not None else None

        out.append(
            {
                "day": d,
                "tavg": _v("temperature_2m_mean"),
                "tmax": _v("temperature_2m_max"),
                "tmin": _v("temperature_2m_min"),
                "precipitation": _v("precipitation_sum"),
                "humidity": _v("relative_humidity_2m_mean"),
                "wind": _v("wind_speed_10m_max"),
            }
        )
    return {"rows": out}
