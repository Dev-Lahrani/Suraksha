"""Per-district climatological baselines (1991-2020) from Open-Meteo archive."""

from __future__ import annotations

import calendar
import logging
from datetime import date

import pandas as pd
from sqlalchemy.orm import Session

from suraksha.db import Climatology, SessionLocal

logger = logging.getLogger(__name__)


def doy_aligned(day: date) -> int:
    """Map calendar day to 1..366 so Mar-Dec aligns across leap/non-leap years."""
    doy = day.timetuple().tm_yday
    if calendar.isleap(day.year) or doy <= 59:
        return doy
    return doy + 1  # shift post-Feb days so 1 Mar = 61 in every year


def compute_climatology(
    district_id: str,
    history: pd.DataFrame,
    db: Session | None = None,
) -> pd.DataFrame:
    """Aggregate a multi-year daily history DataFrame into per-doy normals.

    `history` must have columns: day (date), tavg, precipitation.
    Returns a DataFrame indexed by doy with tavg_normal, rain_normal, rain_p90.
    """
    df = history.copy()
    df["day"] = pd.to_datetime(df["day"])
    df["doy"] = df["day"].dt.date.map(doy_aligned)
    grouped = df.groupby("doy")
    out = pd.DataFrame(
        {
            "tavg_normal": grouped["tavg"].mean(),
            "rain_normal": grouped["precipitation"].mean(),
            "rain_p90": grouped["precipitation"].quantile(0.90),
        }
    ).reset_index()

    own_session = db is None
    db = db or SessionLocal()
    try:
        db.query(Climatology).filter(Climatology.district_id == district_id).delete()
        for _, row in out.iterrows():
            db.add(
                Climatology(
                    district_id=district_id,
                    doy=int(row["doy"]),
                    tavg_normal=_f(row["tavg_normal"]),
                    rain_normal=_f(row["rain_normal"]),
                    rain_p90=_f(row["rain_p90"]),
                )
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        if own_session:
            db.close()
    logger.info("climatology stored for %s (%d doys)", district_id, len(out))
    return out


def _f(x) -> float | None:
    try:
        if x is None or pd.isna(x):
            return None
        return round(float(x), 3)
    except (TypeError, ValueError):
        return None


def climatology_map(district_id: str) -> dict[int, dict[str, float | None]]:
    """Load a district's climatology as {doy: {...}} for fast lookups."""
    with SessionLocal() as db:
        rows = db.query(Climatology).filter(Climatology.district_id == district_id).all()
        return {
            r.doy: {
                "tavg_normal": r.tavg_normal,
                "rain_normal": r.rain_normal,
                "rain_p90": r.rain_p90,
            }
            for r in rows
        }
