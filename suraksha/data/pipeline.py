"""Ingestion + risk-scoring pipeline (idempotent upserts, concurrency-limited)."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import pandas as pd
from sqlalchemy.orm import Session

from suraksha.core.climatology import climatology_map, compute_climatology, doy_aligned
from suraksha.core.risks import compute_risk_for_day
from suraksha.db import AirQuality, District, RiskScore, SessionLocal, WeatherDay
from suraksha.data.open_meteo import fetch_archive, fetch_forecast, fetch_pm25

logger = logging.getLogger(__name__)

CLIMATOLOGY_START = date(1995, 1, 1)
CLIMATOLOGY_END = date(2024, 12, 31)


_pipeline_running = False
_pipeline_status: dict = {"running": False, "last_run": None, "last_error": None}


def pipeline_status() -> dict:
    return dict(_pipeline_status)


async def run_pipeline(force: bool = False) -> dict:
    """Prevent concurrent scheduler/manual runs in this single-worker process."""
    global _pipeline_running
    if _pipeline_running:
        return {"districts": 0, "weather_rows": 0, "aq_rows": 0, "risk_rows": 0,
                "ml_models": 0, "errors": [], "skipped": "already_running"}
    _pipeline_running = True
    _pipeline_status.update(running=True, last_error=None)
    try:
        result = await _run_pipeline(force)
        _pipeline_status["last_run"] = result
        return result
    except Exception as exc:
        _pipeline_status["last_error"] = str(exc)
        raise
    finally:
        _pipeline_running = False
        _pipeline_status["running"] = False


async def _run_pipeline(force: bool = False) -> dict:
    """Full ingestion for every district + risk scoring. Returns a summary dict."""
    with SessionLocal() as db:
        districts = db.query(District).all()
        district_list = [
            {"id": d.id, "lat": d.lat, "lon": d.lon, "name_en": d.name_en} for d in districts
        ]

    errors: list[str] = []
    weather_rows = 0
    aq_rows = 0
    scored = 0
    ml_trained = 0

    async with httpx.AsyncClient() as client:
        sem = asyncio.Semaphore(5)

        async def guarded(d: dict) -> dict | None:
            async with sem:
                try:
                    return await _ingest_district(client, d, force=force)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("ingest failed for %s", d["id"])
                    errors.append(f"{d['id']}: {exc}")
                    return None

        results = await asyncio.gather(*(guarded(d) for d in district_list))

    for res in results:
        if not res:
            continue
        weather_rows += res["weather_rows"]
        aq_rows += res["aq_rows"]
        scored += res["scored"]
        ml_trained += 1 if res["ml_trained"] else 0

    summary = {
        "districts": len(district_list),
        "weather_rows": weather_rows,
        "aq_rows": aq_rows,
        "risk_rows": scored,
        "ml_models": ml_trained,
        "errors": errors,
        "ran_at": datetime.now(timezone.utc).isoformat(),
    }
    logger.info("pipeline done: %s", {k: v for k, v in summary.items() if k != "errors"})
    return summary


async def _ingest_district(client: httpx.AsyncClient, d: dict, force: bool) -> dict:
    """Ingest one district: forecast, AQ, (climatology if missing), risk scores."""
    # 1. Climatology (once per district)
    with SessionLocal() as db:
        from suraksha.db import Climatology  # local import avoids cycles

        has_clim = db.query(Climatology).filter(Climatology.district_id == d["id"]).count() > 0
    if force or not has_clim:
        hist = await fetch_archive(client, d["lat"], d["lon"], CLIMATOLOGY_START, CLIMATOLOGY_END)
        df = pd.DataFrame(hist["rows"])
        df = df.rename(columns={"tavg": "tavg", "precipitation": "precipitation"})
        compute_climatology(d["id"], df[["day", "tavg", "precipitation"]])

    # 2. Weather: past 7 obs + 7-day forecast
    wx = await fetch_forecast(client, d["lat"], d["lon"], days=7, past_days=7)
    weather_rows = _upsert_weather(d["id"], wx["rows"])

    # 3. Air quality (last 48h hourly)
    try:
        aq = await fetch_pm25(client, d["lat"], d["lon"], past_days=2)
        aq_rows = _upsert_aq(d["id"], aq)
    except Exception as exc:  # noqa: BLE001 — AQ is optional, weather is not
        logger.warning("AQ ingest failed for %s: %s", d["id"], exc)
        aq_rows = 0

    # 4. Risk scores
    scored = compute_and_store_risks(d["id"])

    # 5. ML forecaster (optional enhancement — never blocks the pipeline)
    from suraksha.ml.runner import run_forecaster

    ml_trained = run_forecaster(d["id"])

    return {
        "weather_rows": weather_rows,
        "aq_rows": aq_rows,
        "scored": scored,
        "ml_trained": ml_trained,
    }


def _upsert_weather(district_id: str, rows: list[dict]) -> int:
    with SessionLocal() as db:  # type: Session
        existing = {
            w.day: w
            for w in db.query(WeatherDay).filter(WeatherDay.district_id == district_id)
        }
        for r in rows:
            day = date.fromisoformat(r["day"])
            is_forecast = day >= date.today()
            w = existing.get(day)
            if w is None:
                w = WeatherDay(district_id=district_id, day=day)
                db.add(w)
                existing[day] = w
            w.tavg = r["tavg"]
            w.tmax = r["tmax"]
            w.tmin = r["tmin"]
            w.precipitation = r["precipitation"]
            w.humidity = r["humidity"]
            w.wind = r["wind"]
            w.is_forecast = is_forecast
        db.commit()
        return len(rows)


def _upsert_aq(district_id: str, rows: list[dict]) -> int:
    with SessionLocal() as db:  # type: Session
        existing = {
            a.hour: a for a in db.query(AirQuality).filter(AirQuality.district_id == district_id)
        }
        for r in rows:
            if r["pm25"] is None and r["pm10"] is None:
                continue
            a = existing.get(r["hour"])
            if a is None:
                a = AirQuality(district_id=district_id, hour=r["hour"])
                db.add(a)
                existing[r["hour"]] = a
            a.pm25 = r["pm25"]
            a.pm10 = r["pm10"]
        db.commit()
        return len(rows)


def latest_pm25(district_id: str) -> float | None:
    """Mean of available past 24h CAMS readings; never future or stale data."""
    with SessionLocal() as db:
        now = datetime.now(ZoneInfo("Asia/Kolkata")).replace(tzinfo=None)
        rows = db.query(AirQuality).filter(
            AirQuality.district_id == district_id, AirQuality.pm25.isnot(None),
            AirQuality.hour >= (now - timedelta(hours=24)).isoformat(timespec="minutes"),
            AirQuality.hour <= now.isoformat(timespec="minutes"),
        ).all()
        return sum(r.pm25 for r in rows) / len(rows) if rows else None


def compute_and_store_risks(district_id: str) -> int:
    """Score all stored days (obs + forecast) for one district."""
    clim = climatology_map(district_id)
    count = 0
    with SessionLocal() as db:  # type: Session
        rows = (
            db.query(WeatherDay)
            .filter(WeatherDay.district_id == district_id)
            .order_by(WeatherDay.day)
            .all()
        )
        aq_by_day: dict[str, list[float]] = {}
        for aq in db.query(AirQuality).filter(AirQuality.district_id == district_id):
            if aq.pm25 is not None:
                aq_by_day.setdefault(aq.hour[:10], []).append(aq.pm25)
        by_day = {w.day: w for w in rows}
        existing = {
            (r.day, r.hazard): r
            for r in db.query(RiskScore).filter(RiskScore.district_id == district_id)
        }
        for w in rows:
            day_aq = aq_by_day.get(w.day.isoformat(), [])
            pm25 = sum(day_aq) / len(day_aq) if day_aq else None
            rain_values = [by_day[w.day - timedelta(days=k)].precipitation
                           for k in range(3) if w.day - timedelta(days=k) in by_day]
            rain_3day = sum(
                by_day[w.day - timedelta(days=k)].precipitation or 0.0
                for k in range(3)
                if (w.day - timedelta(days=k)) in by_day
                and by_day[w.day - timedelta(days=k)].precipitation is not None
            )
            doy = doy_aligned(w.day)
            rain_p90 = (clim.get(doy) or {}).get("rain_p90")
            scores = compute_risk_for_day(
                tmax=w.tmax,
                tavg=w.tavg,
                precipitation=w.precipitation,
                rain_3day=rain_3day if rain_values and all(v is not None for v in rain_values) else None,
                rain_p90=rain_p90,
                humidity=w.humidity,
                pm25=pm25,
            )
            for hazard, res in scores.items():
                if res["score"] is None:
                    stale = existing.get((w.day, hazard))
                    if stale is not None:
                        db.delete(stale)
                    continue
                import json as _json

                r = existing.get((w.day, hazard))
                if r is None:
                    r = RiskScore(district_id=district_id, day=w.day, hazard=hazard)
                    db.add(r)
                r.score = res["score"]
                r.band = res["band"]
                r.detail = _json.dumps(res["detail"])
                count += 1
        db.commit()
    return count
