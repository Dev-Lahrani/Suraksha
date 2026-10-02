"""Regression tests for the end-to-end hackathon audit (no network)."""

import hashlib
import hmac
from datetime import date, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from suraksha.agent import brain
from suraksha.agent.i18n import format_advisory, format_forecast
from suraksha.config import get_settings
from suraksha.data import pipeline
from suraksha.db import District, RiskScore, SessionLocal, WeatherDay
from suraksha.server.app import app


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client


def test_existing_database_upgrade(tmp_path, monkeypatch):
    import suraksha.db as database
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE districts (id VARCHAR PRIMARY KEY, name_en VARCHAR NOT NULL, name_hi VARCHAR, name_mr VARCHAR, state VARCHAR NOT NULL, lat FLOAT NOT NULL, lon FLOAT NOT NULL, population INTEGER)"))
        connection.execute(text("INSERT INTO districts VALUES ('PUNE', 'Pune', '', '', 'Maharashtra', 18.52, 73.86, 0)"))
    monkeypatch.setattr(database, "engine", engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(database, "SessionLocal", factory)
    database.init_db()
    database.init_db()
    assert "name_ta" in {column["name"] for column in inspect(engine).get_columns("districts")}
    with factory() as db:
        assert db.get(District, "PUNE").name_ta
    engine.dispose()


def test_map_uses_today_not_last_forecast(client, clean_pune):
    with SessionLocal() as db:
        db.add_all([RiskScore(district_id="PUNE", day=date.today(), hazard="heat", score=10, band="low"),
                    RiskScore(district_id="PUNE", day=date.today() + timedelta(days=6), hazard="heat", score=90, band="high")])
        db.commit()
    rows = {r["id"]: r for r in client.get("/api/risk-map").json()}
    assert rows["PUNE"]["overall"] == 10
    assert client.get("/api/risk-map?day=invalid").status_code == 422


@pytest.mark.parametrize("path,method", [("advisory", "get"), ("forecast-text", "get"), ("air-quality", "get"), ("voice", "post")])
def test_unknown_district_returns_404(client, path, method):
    assert getattr(client, method)(f"/api/district/NOPE/{path}").status_code == 404


def test_chat_validation(client):
    assert client.post("/api/chat", json=[]).status_code == 422
    assert client.post("/api/chat", json={"message": "x" * 4001}).status_code == 422
    assert client.post("/api/chat", json={"message": " "}).status_code == 400


def test_real_meta_verification(client):
    response = client.get("/webhook/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "suraksha-verify", "hub.challenge": "123"})
    assert response.status_code == 200 and response.text == "123"


def test_webhook_signature(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "whatsapp_app_secret", "test-secret")
    raw = b'{"entry": []}'
    assert client.post("/webhook/whatsapp", content=raw).status_code == 403
    signature = "sha256=" + hmac.new(b"test-secret", raw, hashlib.sha256).hexdigest()
    assert client.post("/webhook/whatsapp", content=raw, headers={"X-Hub-Signature-256": signature}).status_code == 200


def test_admin_key_protects_sweep(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_api_key", "test-key")
    assert client.post("/api/alerts/sweep").status_code == 401
    assert client.post("/api/alerts/sweep", headers={"X-API-Key": "test-key"}).status_code == 200


def test_voice_correct_media_type(client, monkeypatch):
    from suraksha.delivery import voice
    monkeypatch.setattr(voice, "synthesize", AsyncMock(return_value=(b"MP3", True)))
    response = client.post("/api/district/PUNE/voice")
    assert response.headers["content-type"] == "audio/mpeg"


async def test_session_remembers_district_and_language():
    await brain.handle_message("audit-memory", "पुणे में गर्मी का खतरा?")
    reply = await brain.handle_message("audit-memory", "forecast")
    assert "पुणे" in reply and "अगले" in reply


async def test_voice_fallback_does_not_claim_sent():
    reply = await brain.handle_message("audit-voice", "voice Pune")
    assert "unavailable" in reply and "sent as a voice note" not in reply


async def test_llm_invented_number_rejected(monkeypatch):
    monkeypatch.setattr(brain.llm, "chat", AsyncMock(return_value="Risk 999. Sources: made up"))
    assert await brain._llm_ground({"district": {"name_en": "Pune", "state": "Maharashtra"}}, "Risk 20. Sources: Open-Meteo", "en") == "Risk 20. Sources: Open-Meteo"


def test_format_missing_localized_name():
    assert "Pune" in format_advisory({"name_en": "Pune", "state": "Maharashtra"}, [], "ta")
    assert "next 1 days" in format_forecast({"name_en": "Pune", "state": "Maharashtra"}, [{"day": "2026-10-03"}], "en")


def test_zero_rain_is_scored_and_missing_data_removes_old_risk(clean_pune):
    rows = [{"day": date.today().isoformat(), "tavg": 25, "tmax": 30, "tmin": 20, "precipitation": 0, "humidity": 50, "wind": 5}]
    pipeline._upsert_weather("PUNE", rows + rows)
    pipeline.compute_and_store_risks("PUNE")
    with SessionLocal() as db:
        assert db.query(WeatherDay).filter_by(district_id="PUNE").count() == 1
        assert db.query(RiskScore).filter_by(district_id="PUNE", hazard="flood").one().score == 0
    rows[0]["precipitation"] = None
    pipeline._upsert_weather("PUNE", rows)
    pipeline.compute_and_store_risks("PUNE")
    with SessionLocal() as db:
        assert db.query(RiskScore).filter_by(district_id="PUNE", hazard="flood").count() == 0


def test_demo_end_to_end(tmp_path, monkeypatch):
    import suraksha.db as database
    import suraksha.data.demo as demo
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite:///{tmp_path / 'demo.db'}", connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", factory)
    monkeypatch.setattr(demo, "SessionLocal", factory)
    monkeypatch.setattr(pipeline, "SessionLocal", factory)
    monkeypatch.setattr(get_settings(), "database_url", f"sqlite:///{tmp_path / 'demo.db'}")
    database.init_db()
    demo.seed_demo()
    demo.seed_demo()
    with factory() as db:
        assert db.query(District).count() == 42
        assert db.query(WeatherDay).count() == 42 * 14
        assert db.query(RiskScore).filter_by(band="high").count() > 0
    engine.dispose()


def test_demo_requires_separate_database():
    from suraksha.data.demo import seed_demo
    with pytest.raises(ValueError, match="separate"):
        seed_demo()
