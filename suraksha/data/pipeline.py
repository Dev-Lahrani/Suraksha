"""Ingestion + risk-scoring pipeline (idempotent upserts, concurrency-limited)."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import pandas as pd
from sqlalchemy.orm import Session

from suraksha.core.clock import india_today
from suraksha.core.climatology import climatology_map, compute_climatology, doy_aligned
from suraksha.core.risks import compute_risk_for_day
from suraksha.db import AirQuality, District, RiskScore, SessionLocal, WeatherDay
from suraksha.data.open_meteo import fetch_archive, fetch_forecast, fetch_pm25

logger = logging.getLogger(__name__)

CLIMATOLOGY_START = date(1995, 1, 1)
CLIMATOLOGY_END = date(2024, 12, 31)
# Forecast API serves up to 92 past days (the oldest ones can be empty).
OBSERVED_DAYS = 92
HISTORY_BACKFILL_DAYS = 400
# After the archive exhausts its retries, skip it for a while instead of
# queueing every remaining district behind the same rate limit.
ARCHIVE_COOLDOWN_SECONDS = 600
_archive_retry_at = 0.0


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
                    return await _ingest_district(client, d)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("ingest failed for %s", d["id"])
                    errors.append(f"{d['id']}: {exc}")
                    return None

        # Phase 1 — current weather, air quality and scores for every district.
        results = await asyncio.gather(*(guarded(d) for d in district_list))
        # Phase 2 — climatology, history backfill and ML. The archive API is
        # serialized and often rate limited, so it never delays phase 1.
        for d, res in zip(district_list, results):
            if res:
                try:
                    await _enrich_district(client, d, res, force=force)
                except Exception:  # noqa: BLE001 — enhancement only
                    logger.exception("enrichment failed for %s", d["id"])

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


async def _ingest_district(client: httpx.AsyncClient, d: dict) -> dict:
    """Phase 1 for one district: forecast, AQ and risk scores.

    Flood scoring uses a default heavy-rain threshold until the district's
    climatology exists; `_enrich_district` re-scores once it lands.
    """
    # 1. Weather: recent observations + 7-day forecast
    wx = await fetch_forecast(client, d["lat"], d["lon"], days=7, past_days=OBSERVED_DAYS)
    weather_rows = _upsert_weather(d["id"], wx["rows"])

    # 2. Air quality (last 48h hourly)
    try:
        aq = await fetch_pm25(client, d["lat"], d["lon"], past_days=2)
        aq_rows = _upsert_aq(d["id"], aq)
    except Exception as exc:  # noqa: BLE001 — AQ is optional, weather is not
        logger.warning("AQ ingest failed for %s: %s", d["id"], exc)
        aq_rows = 0

    # 3. Risk scores
    scored = compute_and_store_risks(d["id"])

    return {"weather_rows": weather_rows, "aq_rows": aq_rows, "scored": scored, "ml_trained": False}


async def _enrich_district(client: httpx.AsyncClient, d: dict, res: dict, force: bool) -> None:
    """Phase 2 for one district: climatology (once), observed-history backfill, ML."""
    global _archive_retry_at
    from suraksha.db import Climatology  # local import avoids cycles
    from suraksha.ml.runner import MIN_HISTORY_DAYS, run_forecaster

    with SessionLocal() as db:
        has_clim = db.query(Climatology).filter(Climatology.district_id == d["id"]).count() > 0
        observed = db.query(WeatherDay).filter(
            WeatherDay.district_id == d["id"], WeatherDay.is_forecast.is_(False),
            WeatherDay.tavg.isnot(None), WeatherDay.precipitation.isnot(None)).count()
    need_clim = force or not has_clim
    # The forecast API's past days start with gaps, so the forecaster's history
    # comes from the tail of the archive (one request serves both needs).
    need_history = observed < MIN_HISTORY_DAYS + 30
    if (need_clim or need_history) and time.monotonic() >= _archive_retry_at:
        yesterday = india_today() - timedelta(days=1)
        start = CLIMATOLOGY_START if need_clim else yesterday - timedelta(days=HISTORY_BACKFILL_DAYS)
        try:
            hist = await fetch_archive(client, d["lat"], d["lon"], start, yesterday)
        except Exception as exc:  # noqa: BLE001 — retried on a later pass
            _archive_retry_at = time.monotonic() + ARCHIVE_COOLDOWN_SECONDS
            logger.warning("archive unavailable for %s (%s); keeping default-threshold scores", d["id"], exc)
        else:
            if need_clim:
                df = pd.DataFrame(hist["rows"])
                df = df[df["day"] <= CLIMATOLOGY_END.isoformat()]
                await asyncio.to_thread(compute_climatology, d["id"], df[["day", "tavg", "precipitation"]])
                has_clim = True
            _backfill_observed(d["id"], hist["rows"][-HISTORY_BACKFILL_DAYS:])
            res["scored"] = compute_and_store_risks(d["id"])

    # ML forecaster (optional enhancement — never blocks the pipeline).
    # Anomaly targets are meaningless without the district's own normals.
    if has_clim:
        res["ml_trained"] = await asyncio.to_thread(run_forecaster, d["id"])


def _backfill_observed(district_id: str, rows: list[dict]) -> int:
    """Add archive days that are not stored yet; never overwrite fresher rows."""
    added = 0
    with SessionLocal() as db:
        known = {day for (day,) in db.query(WeatherDay.day).filter(WeatherDay.district_id == district_id)}
        for r in rows:
            day = date.fromisoformat(r["day"])
            # ERA5 lags a few days: its newest rows are empty.
            if day in known or day >= india_today() or r["tavg"] is None or r["precipitation"] is None:
                continue
            db.add(WeatherDay(district_id=district_id, day=day, tavg=r["tavg"], tmax=r["tmax"], tmin=r["tmin"],
                              precipitation=r["precipitation"], humidity=r["humidity"], wind=r["wind"],
                              is_forecast=False))
            added += 1
        db.commit()
    return added


def _upsert_weather(district_id: str, rows: list[dict]) -> int:
    with SessionLocal() as db:  # type: Session
        existing = {
            w.day: w
            for w in db.query(WeatherDay).filter(WeatherDay.district_id == district_id)
        }
        for r in rows:
            day = date.fromisoformat(r["day"])
            is_forecast = day >= india_today()
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
