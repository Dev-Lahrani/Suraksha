"""Bridge between the GBM forecaster and the pipeline.

Per decision.md D12 the forecaster is an *enhancement*, never a dependency:
it predicts next-day temperature (as anomalies vs climatology) and rainfall,
and its output is only surfaced when evaluate() shows it beats the climatology
baseline (validate-or-withhold). Pickled models live in the `model_runs` table
so a district keeps serving its last honest model until a better one lands.

Every entry point degrades gracefully: no data, short history or a training
failure simply yields no ML rows — the product runs on Open-Meteo forecasts.
"""

from __future__ import annotations

import base64
import logging
import pickle
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from suraksha.core.climatology import climatology_map
from suraksha.core.forecaster import predict, train
from suraksha.db import ModelRun, SessionLocal, WeatherDay

logger = logging.getLogger(__name__)

RETRAIN_AFTER_HOURS = 24  # hourly pipeline must not retrain GBMs every pass


def load_history(district_id: str, max_days: int = 730) -> pd.DataFrame | None:
    """Observed daily weather for one district as a DataFrame (None if too little)."""
    with SessionLocal() as db:
        rows = (
            db.query(WeatherDay)
            .filter(
                WeatherDay.district_id == district_id,
                WeatherDay.is_forecast.is_(False),
            )
            .order_by(WeatherDay.day.desc())
            .limit(max_days)
            .all()
        )
        if len(rows) < 90:
            return None
        return pd.DataFrame(
            [
                {
                    "day": w.day.isoformat(),
                    "tavg": w.tavg,
                    "precipitation": w.precipitation,
                    "humidity": w.humidity,
                    "wind": w.wind,
                }
                for w in reversed(rows)  # oldest → newest
            ]
        )


def run_forecaster(district_id: str) -> bool:
    """Train + evaluate + persist one district's models.

    The ModelRun row is written only when the model beats the climatology
    baseline; otherwise any stale row is left untouched (withhold rule).
    Retraining is throttled to once per RETRAIN_AFTER_HOURS.
    Returns True when a validated model is available.
    """
    try:
        if _has_fresh_model(district_id):
            return True
        hist = load_history(district_id)
        if hist is None:
            return False
        clim = climatology_map(district_id)
        models = train(hist, clim)
        if models is None or not models.get("mae"):
            return False
        mae = models["mae"]
        beats_t = mae["mae_tavg_t1"] < mae["mae_baseline_tavg_t1"]
        beats_r = mae["mae_rain_t1"] < mae["mae_baseline_rain_t1"]
        if not (beats_t or beats_r):
            logger.info(
                "forecaster withheld for %s (t %.3f vs %.3f, r %.3f vs %.3f)",
                district_id,
                mae["mae_tavg_t1"], mae["mae_baseline_tavg_t1"],
                mae["mae_rain_t1"], mae["mae_baseline_rain_t1"],
            )
            return False
        payload = base64.b64encode(pickle.dumps(models)).decode("ascii")
        with SessionLocal() as db:
            run = db.get(ModelRun, district_id)
            if run is None:
                run = ModelRun(district_id=district_id)
                db.add(run)
            run.trained_at = datetime.now(timezone.utc).isoformat()
            run.payload = payload
            run.mae_tavg = mae["mae_tavg_t1"]
            run.mae_tavg_baseline = mae["mae_baseline_tavg_t1"]
            run.mae_rain = mae["mae_rain_t1"]
            run.mae_rain_baseline = mae["mae_baseline_rain_t1"]
            db.commit()
        logger.info("forecaster stored for %s (mae_t %.3f, mae_r %.3f)", district_id, mae["mae_tavg_t1"], mae["mae_rain_t1"])
        return True
    except Exception:  # noqa: BLE001 — ML must never break the pipeline
        logger.exception("forecaster training failed for %s", district_id)
        return False


def _has_fresh_model(district_id: str) -> bool:
    """True when a stored model exists and was trained within the throttle window."""
    with SessionLocal() as db:
        run = db.get(ModelRun, district_id)
        if run is None or not run.trained_at:
            return False
        try:
            trained = datetime.fromisoformat(run.trained_at)
        except ValueError:
            return False
        age_hours = (datetime.now(timezone.utc) - trained).total_seconds() / 3600
        return age_hours < RETRAIN_AFTER_HOURS


def ml_outlook(district_id: str, days: int = 5) -> list[dict] | None:
    """Recursive 5-day ML outlook from the stored model (None when absent)."""
    try:
        with SessionLocal() as db:
            run = db.get(ModelRun, district_id)
        if run is None:
            return None
        models = pickle.loads(base64.b64decode(run.payload))
        hist = load_history(district_id)
        if hist is None:
            return None
        clim = climatology_map(district_id)
        start = date.today() + timedelta(days=1)
        rows = predict(models, hist, clim, start=start, days=days)
        return rows or None
    except Exception:  # noqa: BLE001
        logger.exception("ml_outlook failed for %s", district_id)
        return None


def model_summary(district_id: str) -> dict | None:
    """Validation metadata for the dashboard ('why should I trust this?')."""
    with SessionLocal() as db:
        run = db.get(ModelRun, district_id)
        if run is None:
            return None
        return {
            "trained_at": run.trained_at,
            "mae_tavg": run.mae_tavg,
            "mae_tavg_baseline": run.mae_tavg_baseline,
            "mae_rain": run.mae_rain,
            "mae_rain_baseline": run.mae_rain_baseline,
        }
