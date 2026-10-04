"""Command-center feature contracts and language flows (fully offline)."""
import asyncio
import csv
import io
from suraksha.core.clock import india_today
from datetime import date, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from suraksha.agent import brain
from suraksha.agent.i18n import detect_language, format_forecast, language_catalog, playbook_actions
from suraksha.agent.tools import find_district
from suraksha.data import pipeline
from suraksha.db import RiskScore, SessionLocal, WeatherDay
from suraksha.server.app import app


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client


@pytest.fixture
def insights_data(clean_pune):
    with SessionLocal() as db:
        db.add_all([
            WeatherDay(district_id="PUNE", day=india_today(), tavg=30, tmax=38, precipitation=0, is_forecast=True),
            WeatherDay(district_id="PUNE", day=india_today()-timedelta(days=3), tavg=27, tmax=32, precipitation=2, is_forecast=False),
            RiskScore(district_id="PUNE", day=india_today(), hazard="heat", score=75, band="high", detail='{}'),
            RiskScore(district_id="PUNE", day=india_today(), hazard="flood", score=0, band="low", detail='{}'),
        ])
        db.commit()


def test_overview_counts(client, insights_data):
    data = client.get("/api/overview").json()
    assert data["districts"] == 42
    assert data["high"] >= 1
    assert data["covered"] + data["unknown"] == 42
    assert data["high"] + data["moderate"] + data["low"] == data["covered"]
    assert data["population_in_high_risk_districts"] > 0
    assert client.get("/api/overview?day=garbage").status_code == 422


def test_history_and_csv(client, insights_data):
    response = client.get("/api/district/PUNE/history?days=30")
    assert response.status_code == 200
    rows = response.json()["rows"]
    assert len(rows) == 2 and rows[0]["day"] < rows[1]["day"]
    assert rows[1]["risks"]["flood"]["score"] == 0
    assert len(client.get("/api/district/PUNE/history?days=1").json()["rows"]) == 1
    export = client.get("/api/district/PUNE/export.csv")
    parsed = list(csv.DictReader(io.StringIO(export.text)))
    assert len(parsed) == 2 and parsed[1]["flood_score"] == "0.0"
    assert "PUNE-climate.csv" in export.headers["content-disposition"]
    assert client.get("/api/district/PUNE/history?days=0").status_code == 422
    assert client.get("/api/district/NOPE/export.csv").status_code == 404
    assert client.get("/api/district/NOPE/history").status_code == 404


def test_compare_contract(client, insights_data):
    data = client.get("/api/compare?ids=PUNE,NAGPUR").json()
    assert len(data["districts"]) == 2
    assert data["districts"][0]["hazards"][0]["score"] == 75
    assert client.get("/api/compare?ids=PUNE,PUNE").status_code == 422
    assert client.get("/api/compare?ids=PUNE,NOPE").status_code == 404
    assert client.get("/api/compare?ids=PUNE,NAGPUR,CHENNAI,JAIPUR,PATNA").status_code == 422


def test_nearest_lookup(client):
    data = client.get("/api/nearest?lat=18.52&lon=73.86").json()
    assert data["id"] == "PUNE" and data["distance_km"] == 0
    assert client.get("/api/nearest?lat=100&lon=0").status_code == 422


@pytest.mark.parametrize("code,text,district", [
    ("gu", "પુણેમાં ગરમી", "PUNE"), ("pa", "ਚੰਡੀਗੜ੍ਹ ਵਿੱਚ ਗਰਮੀ", "CHANDIGARH"),
    ("ml", "വയനാട് മഴ", "WAYANAD"), ("ur", "دہلی میں گرمی", "DELHI_NW"),
])
async def test_new_language_chat(code, text, district):
    assert detect_language(text) == code
    with SessionLocal() as db:
        assert find_district(text, db).id == district
    reply = await brain.handle_message("language-test-" + code, text)
    assert "🛡️" in reply
    assert playbook_actions("flood", "high", code)
    forecast = format_forecast({"name_en": "Pune", "state": "Maharashtra"}, [], code)
    assert "Pune" in forecast


def test_language_catalog_and_checklists(client):
    catalog = client.get("/api/languages").json()
    assert len(catalog) == 11
    assert next(l for l in catalog if l["code"] == "ur")["direction"] == "rtl"
    for language in language_catalog():
        for hazard in ("heat", "flood", "air"):
            data = client.get(f"/api/preparedness?hazard={hazard}&lang={language['code']}").json()
            assert data["actions"] and len({a["id"] for a in data["actions"]}) == len(data["actions"])
    assert client.get("/api/preparedness?hazard=invalid").status_code == 422


def test_chat_explicit_language(client):
    response = client.post("/api/chat", json={"message":"Pune advisory", "session_id":"explicit-urdu", "language":"ur"})
    assert response.status_code == 200 and "حفاظتی" in response.json()["reply"]
    assert client.post("/api/chat", json={"message":"Pune", "language":"invalid"}).status_code == 422


async def test_pipeline_overlap_and_cleanup(monkeypatch):
    started, release = asyncio.Event(), asyncio.Event()
    async def run(force):
        started.set()
        await release.wait()
        return {"errors":[]}
    monkeypatch.setattr(pipeline,"_run_pipeline",run)
    first = asyncio.create_task(pipeline.run_pipeline())
    await started.wait()
    assert pipeline.pipeline_status()["running"]
    assert (await pipeline.run_pipeline())["skipped"] == "already_running"
    release.set()
    await first
    assert not pipeline.pipeline_status()["running"]
    monkeypatch.setattr(pipeline,"_run_pipeline",AsyncMock(side_effect=RuntimeError("test")))
    with pytest.raises(RuntimeError):
        await pipeline.run_pipeline()
    assert not pipeline.pipeline_status()["running"]


def test_frontend_assets_no_cdn(client):
    html = client.get("/").text
    assert "District explorer" in html and "Compare districts" in html
    assert "cdn." not in html and "unpkg" not in html
    assert client.get("/styles.css").status_code == 200
    assert client.get("/app.js").status_code == 200
