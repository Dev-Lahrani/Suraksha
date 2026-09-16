"""Database layer: engine, session factory, ORM models and schema init/seed."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from suraksha.config import get_settings

Base = declarative_base()


class District(Base):
    __tablename__ = "districts"
    id = Column(String, primary_key=True)
    name_en = Column(String, nullable=False)
    name_hi = Column(String, default="")
    name_mr = Column(String, default="")
    state = Column(String, nullable=False)
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    population = Column(Integer, default=0)


class WeatherDay(Base):
    """Observed (past) and forecast (future) daily weather per district."""

    __tablename__ = "weather_days"
    id = Column(Integer, primary_key=True, autoincrement=True)
    district_id = Column(String, ForeignKey("districts.id"), nullable=False)
    day = Column(Date, nullable=False)
    tavg = Column(Float)  # mean temperature °C
    tmax = Column(Float)
    tmin = Column(Float)
    precipitation = Column(Float)  # mm/day
    humidity = Column(Float)  # %
    wind = Column(Float)  # km/h
    is_forecast = Column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("district_id", "day", name="uq_district_day"),)


class Climatology(Base):
    """30-year per-calendar-day baselines used for anomaly & percentile math."""

    __tablename__ = "climatology"
    id = Column(Integer, primary_key=True, autoincrement=True)
    district_id = Column(String, ForeignKey("districts.id"), nullable=False)
    doy = Column(Integer, nullable=False)  # 1..366
    tavg_normal = Column(Float)
    rain_normal = Column(Float)
    rain_p90 = Column(Float)  # 90th percentile daily precipitation for that doy
    __table_args__ = (UniqueConstraint("district_id", "doy", name="uq_district_doy"),)


class RiskScore(Base):
    __tablename__ = "risk_scores"
    id = Column(Integer, primary_key=True, autoincrement=True)
    district_id = Column(String, ForeignKey("districts.id"), nullable=False)
    day = Column(Date, nullable=False)
    hazard = Column(String, nullable=False)  # heat | flood | air
    score = Column(Float)  # 0..100
    band = Column(String)  # low | moderate | high
    detail = Column(String)  # JSON blob of drivers
    __table_args__ = (UniqueConstraint("district_id", "day", "hazard", name="uq_risk"),)


class AirQuality(Base):
    __tablename__ = "air_quality"
    id = Column(Integer, primary_key=True, autoincrement=True)
    district_id = Column(String, ForeignKey("districts.id"), nullable=False)
    hour = Column(String, nullable=False)  # ISO timestamp (UTC)
    pm25 = Column(Float)
    pm10 = Column(Float)
    __table_args__ = (UniqueConstraint("district_id", "hour", name="uq_aq"),)


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    id = Column(String, primary_key=True)  # phone number or web session id
    language = Column(String, default="en")
    district_id = Column(String, ForeignKey("districts.id"), nullable=True)
    created_at = Column(String, nullable=True)


class Subscriber(Base):
    """A WhatsApp/web user who asked to receive proactive alerts for one district."""

    __tablename__ = "subscribers"
    id = Column(String, primary_key=True)  # phone number (WhatsApp) or web session id
    district_id = Column(String, ForeignKey("districts.id"), nullable=False)
    language = Column(String, default="en")
    active = Column(Boolean, default=True)
    created_at = Column(String, nullable=True)
    last_alerted_day = Column(String, nullable=True)  # ISO date of last alert push (dedupe)


class AlertLog(Base):
    """One proactive push per (subscriber, district-day, reason) — audit + dedupe."""

    __tablename__ = "alert_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    subscriber_id = Column(String, nullable=False)
    district_id = Column(String, nullable=False)
    day = Column(Date, nullable=False)
    reason = Column(String, nullable=False)  # high_risk:<hazard> | anomaly:<kind>
    channel = Column(String, default="whatsapp")
    sent_at = Column(String, nullable=True)  # ISO timestamp
    __table_args__ = (UniqueConstraint("subscriber_id", "day", "reason", name="uq_alert"),)


class ModelRun(Base):
    """Per-district ML forecaster artifact — present only when the GBM beat
    the climatology baseline (validate-or-withhold rule, decision.md D12)."""

    __tablename__ = "model_runs"
    district_id = Column(String, ForeignKey("districts.id"), primary_key=True)
    trained_at = Column(String, nullable=False)  # ISO timestamp (UTC)
    payload = Column(String, nullable=False)     # pickled models dict (base64)
    mae_tavg = Column(Float)                     # model MAE, next-day tavg (°C)
    mae_tavg_baseline = Column(Float)            # climatology baseline MAE
    mae_rain = Column(Float)                     # model MAE, next-day rain (mm)
    mae_rain_baseline = Column(Float)


def _engine_url() -> str:
    url = get_settings().database_url
    if url.startswith("sqlite:///"):
        db_path = Path(url.replace("sqlite:///", "", 1))
        db_path.parent.mkdir(parents=True, exist_ok=True)
    return url


engine = create_engine(
    _engine_url(),
    connect_args={"check_same_thread": False}
    if get_settings().database_url.startswith("sqlite")
    else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """Create tables and seed the district registry from resources."""
    Base.metadata.create_all(engine)
    districts_file = Path(__file__).resolve().parents[1] / "resources" / "districts.json"
    data = json.loads(districts_file.read_text(encoding="utf-8"))
    with SessionLocal() as db:  # type: Session
        for d in data["districts"]:
            if db.get(District, d["id"]) is None:
                db.add(District(**d))
        db.commit()


def get_db():
    """FastAPI dependency yielding a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
