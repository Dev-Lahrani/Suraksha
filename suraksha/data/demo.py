"""Synthetic offline demo data, stored only in a dedicated demo database."""

from datetime import timedelta
from suraksha.core.clock import india_today

from suraksha.data.pipeline import _upsert_weather, compute_and_store_risks
from suraksha.db import Climatology, District, RiskScore, SessionLocal, WeatherDay


def seed_demo() -> None:
    from suraksha.config import get_settings

    if "demo" not in get_settings().database_url:
        raise ValueError("DEMO_MODE requires a separate DATABASE_URL containing 'demo'")
    with SessionLocal() as db:
        districts = db.query(District).order_by(District.id).all()
        existing = {(row.district_id, row.doy) for row in db.query(Climatology).all()}
        for district in districts:
            for doy in range(1, 367):
                if (district.id, doy) not in existing:
                    db.add(Climatology(district_id=district.id, doy=doy,
                                      tavg_normal=27.0, rain_normal=4.0, rain_p90=30.0))
        # demo.db is reused across days: drop rows outside today's window so an
        # earlier launch's synthetic days never leak into history, CSV or trends.
        first, last = india_today() - timedelta(days=7), india_today() + timedelta(days=6)
        for model in (WeatherDay, RiskScore):
            db.query(model).filter((model.day < first) | (model.day > last)).delete(synchronize_session=False)
        db.commit()
    for index, district in enumerate(districts):
        rows = []
        for offset in range(-7, 7):
            hot = index % 5 == 0
            rainy = index % 7 == 0
            rows.append({
                "day": (india_today() + timedelta(days=offset)).isoformat(),
                "tavg": 34.0 if hot else 27.0,
                "tmax": 42.0 if hot else 31.0,
                "tmin": 25.0,
                "precipitation": 80.0 if rainy and offset in (0, 1, 2) else 2.0,
                "humidity": 65.0,
                "wind": 12.0,
            })
        _upsert_weather(district.id, rows)
        compute_and_store_risks(district.id)
