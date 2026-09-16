"""Forecaster tests on synthetic seasonal data (no network).

Climatology is provided as the TRUE seasonal curve (as ERA5 effectively gives
us with 30 samples per day-of-year). Estimating climatology from a single year
of data is a degenerate case that no model could beat — that regime is
excluded from scope by design (production always uses 1995–2024 baselines).
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd

from suraksha.core.climatology import doy_aligned
from suraksha.core.forecaster import build_frame, predict, train


def _true_clim() -> dict:
    """Analytic seasonal climatology: the ground truth the generator uses."""
    clim = {}
    for doy in range(1, 367):
        clim[doy] = {
            "tavg_normal": 27 + 6 * np.sin(2 * np.pi * (doy - 120) / 366.0),
            "rain_normal": 6.0 if 150 < doy < 270 else 0.5,
            "rain_p90": 15.0 if 150 < doy < 270 else 1.5,
        }
    return clim


def _synthetic_history(days: int = 500) -> pd.DataFrame:
    """Seasonal signal + AR(1) anomalies: yesterday's anomaly predicts today's,
    so a feature-using model *can* and *must* beat climatology."""
    start = date(2024, 1, 1)
    rows = []
    rng = np.random.default_rng(42)
    anom = 0.0
    for i in range(days):
        d = start + timedelta(days=i)
        doy = doy_aligned(d)
        seasonal = 27 + 6 * np.sin(2 * np.pi * (doy - 120) / 366.0)
        anom = 0.65 * anom + rng.normal(0, 0.5)
        rain = max(0.0, rng.gamma(0.6, 4.0) if 150 < doy < 270 else rng.gamma(0.3, 0.5))
        rows.append(
            {
                "day": d.isoformat(),
                "tavg": seasonal + anom,
                "precipitation": rain,
                "humidity": 60 + 15 * np.sin(2 * np.pi * (doy - 150) / 366.0),
                "wind": 8 + rng.normal(0, 2),
            }
        )
    return pd.DataFrame(rows)


def test_build_frame_has_features_and_targets():
    hist = _synthetic_history()
    df = build_frame(hist, _true_clim())
    assert {"t_anom", "rain_lag1", "tavg_t1", "rain_t1", "t_anom_t1"} <= set(df.columns)
    assert len(df) > 300


def test_train_too_short_returns_none():
    hist = _synthetic_history(60)
    assert train(hist, _true_clim()) is None


def test_model_beats_climatology_baseline():
    hist = _synthetic_history(500)
    models = train(hist, _true_clim())
    assert models is not None
    mae = models["mae"]
    assert mae["mae_tavg_t1"] < mae["mae_baseline_tavg_t1"]
    # with true climatology + AR(1) anomalies, MAE should be well under 0.6°C
    assert mae["mae_tavg_t1"] < 0.6


def test_predict_recursive_five_days():
    hist = _synthetic_history(500)
    models = train(hist, _true_clim())
    preds = predict(models, hist, _true_clim(), start=date(2026, 2, 5), days=5)
    assert len(preds) == 5
    assert all("tavg" in p and "precipitation" in p for p in preds)
    assert all(p["precipitation"] >= 0 for p in preds)


def test_predict_without_models_is_empty():
    hist = _synthetic_history(50)
    assert predict(None, hist, _true_clim(), start=date(2026, 2, 5), days=3) == []
