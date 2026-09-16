"""Lightweight ML forecaster: gradient-boosted next-day temperature & rainfall.

Design constraints:
- The model predicts the *anomaly vs climatology*, so it only learns what
  climatology cannot explain — a much easier, more honest task.
- Must beat a climatology baseline in evaluate() or it doesn't ship.
- Falls back to None when there is too little history; callers then rely on
  Open-Meteo forecast values directly.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor

from suraksha.core.climatology import doy_aligned

logger = logging.getLogger(__name__)

FEATURES = [
    "t_anom",
    "rain",
    "rain_lag1",
    "rain_lag2",
    "hum",
    "wind",
    "sin_doy",
    "cos_doy",
    "tavg_normal_t1",
    "rain_normal_t1",
]


def build_frame(history: pd.DataFrame, clim: dict[int, dict[str, float | None]]) -> pd.DataFrame:
    """Feature-engineer a history frame (columns: day,tavg,precipitation,humidity,wind)."""
    df = history.copy()
    df["day"] = pd.to_datetime(df["day"])
    df = df.sort_values("day").reset_index(drop=True)
    df["doy"] = df["day"].dt.date.map(doy_aligned)
    df["tavg_normal"] = df["doy"].map(lambda d: (clim.get(d) or {}).get("tavg_normal"))
    df["rain_normal"] = df["doy"].map(lambda d: (clim.get(d) or {}).get("rain_normal"))
    df["t_anom"] = df["tavg"] - df["tavg_normal"]
    df["rain"] = df["precipitation"]
    df["hum"] = df["humidity"]
    df["rain_lag1"] = df["rain"].shift(1)
    df["rain_lag2"] = df["rain"].shift(2)
    df["sin_doy"] = np.sin(2 * np.pi * df["doy"] / 366.0)
    df["cos_doy"] = np.cos(2 * np.pi * df["doy"] / 366.0)
    # targets = next day values (temperature as anomaly vs next-day normal)
    df["tavg_t1"] = df["tavg"].shift(-1)
    df["rain_t1"] = df["rain"].shift(-1)
    df["tavg_normal_t1"] = df["doy"].map(
        lambda d: (clim.get(d % 366 + 1) or {}).get("tavg_normal")
    )
    df["rain_normal_t1"] = df["doy"].map(
        lambda d: (clim.get(d % 366 + 1) or {}).get("rain_normal")
    )
    df["t_anom_t1"] = df["tavg_t1"] - df["tavg_normal_t1"]
    return df.dropna(subset=FEATURES + ["tavg_t1", "rain_t1", "t_anom_t1"])


def train(history: pd.DataFrame, clim: dict[int, dict[str, float | None]]) -> dict | None:
    """Train next-day models; returns None when history is too short."""
    df = build_frame(history, clim)
    if len(df) < 90:
        logger.info("forecaster: insufficient history (%d rows), falling back", len(df))
        return None
    X = df[FEATURES].to_numpy(dtype=float)
    models = {
        # temperature model predicts the anomaly; climatology is added back at predict time
        "t_anom": GradientBoostingRegressor(n_estimators=250, max_depth=3, learning_rate=0.05),
        "precip": GradientBoostingRegressor(n_estimators=250, max_depth=3, learning_rate=0.05),
        "mae": {},
    }
    models["t_anom"].fit(X, df["t_anom_t1"].to_numpy(dtype=float))
    models["precip"].fit(X, np.clip(df["rain_t1"].to_numpy(dtype=float), 0, None))
    models["mae"] = evaluate(df)
    return models


def evaluate(df: pd.DataFrame) -> dict[str, float]:
    """Hold-out MAE on the last 30 rows vs a climatology-persistence baseline."""
    test = df.tail(30)
    train_df = df.iloc[:-30]
    if len(train_df) < 60:
        return {}
    out: dict[str, float] = {}
    # --- temperature: model anomaly + next-day normal vs next-day normal baseline ---
    m = GradientBoostingRegressor(n_estimators=200, max_depth=3, learning_rate=0.05)
    m.fit(train_df[FEATURES].to_numpy(dtype=float), train_df["t_anom_t1"].to_numpy(dtype=float))
    pred_anom = m.predict(test[FEATURES].to_numpy(dtype=float))
    pred_abs = pred_anom + test["tavg_normal_t1"].to_numpy(dtype=float)
    y = test["tavg_t1"].to_numpy(dtype=float)
    base = test["tavg_normal_t1"].to_numpy(dtype=float)
    out["mae_tavg_t1"] = round(float(np.mean(np.abs(pred_abs - y))), 3)
    out["mae_baseline_tavg_t1"] = round(float(np.mean(np.abs(base - y))), 3)
    # --- rain: model absolute mm vs next-day normal baseline ---
    m2 = GradientBoostingRegressor(n_estimators=200, max_depth=3, learning_rate=0.05)
    m2.fit(
        train_df[FEATURES].to_numpy(dtype=float),
        np.clip(train_df["rain_t1"].to_numpy(dtype=float), 0, None),
    )
    pred_rain = m2.predict(test[FEATURES].to_numpy(dtype=float))
    y_rain = test["rain_t1"].to_numpy(dtype=float)
    base_rain = np.clip(test["rain_normal_t1"].to_numpy(dtype=float), 0, None)
    out["mae_rain_t1"] = round(float(np.mean(np.abs(pred_rain - y_rain))), 3)
    out["mae_baseline_rain_t1"] = round(float(np.mean(np.abs(base_rain - y_rain))), 3)
    return out


def predict(
    models: dict,
    recent: pd.DataFrame,
    clim: dict[int, dict[str, float | None]],
    start: date,
    days: int = 5,
) -> list[dict]:
    """Recursive multi-step forecast returning [{day, tavg, precipitation}]."""
    if models is None:
        return []
    hist = recent.copy()
    hist["day"] = pd.to_datetime(hist["day"])
    hist = hist.sort_values("day")
    preds: list[dict] = []
    day = start
    for _ in range(days):
        row = _next_features(hist, clim, day)
        if row is None:
            break
        X = np.array([[row[f] for f in FEATURES]], dtype=float)
        t_anom = float(models["t_anom"].predict(X)[0])
        tavg = row["tavg_normal_t1"] + t_anom
        rain = max(0.0, float(models["precip"].predict(X)[0]))
        preds.append(
            {"day": day.isoformat(), "tavg": round(tavg, 2), "precipitation": round(rain, 2)}
        )
        hist = pd.concat(
            [
                hist,
                pd.DataFrame(
                    [
                        {
                            "day": pd.Timestamp(day),
                            "tavg": tavg,
                            "precipitation": rain,
                            "humidity": row["hum"],
                            "wind": row["wind"],
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )
        day = day + timedelta(days=1)
    return preds


def _next_features(
    hist: pd.DataFrame, clim: dict[int, dict[str, float | None]], day: date
) -> dict[str, float] | None:
    last = hist.iloc[-1]
    doy = doy_aligned(day)
    nxt = clim.get(doy % 366 + 1) or {}
    cur = clim.get(doy_aligned(pd.Timestamp(last["day"]).date())) or {}
    t_anom = last["tavg"] - (cur.get("tavg_normal") or last["tavg"])
    rain_hist = hist["precipitation"].tail(3).tolist()
    while len(rain_hist) < 3:
        rain_hist.insert(0, 0.0)
    return {
        "t_anom": 0.0 if pd.isna(t_anom) else float(t_anom),
        "rain": float(last["precipitation"]),
        "rain_lag1": float(rain_hist[-2]),
        "rain_lag2": float(rain_hist[-3]),
        "hum": float(last.get("humidity") or 60.0),
        "wind": float(last.get("wind") or 8.0),
        "sin_doy": float(np.sin(2 * np.pi * doy / 366.0)),
        "cos_doy": float(np.cos(2 * np.pi * doy / 366.0)),
        "tavg_normal_t1": float(nxt.get("tavg_normal") or last["tavg"]),
        "rain_normal_t1": float(nxt.get("rain_normal") or 0.0),
    }
