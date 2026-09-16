"""FastAPI endpoint tests (offline; uses the seeded test database)."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from suraksha.db import RiskScore, SessionLocal
from suraksha.server.app import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def seeded_pune_risks():
    with SessionLocal() as db:
        today = date.today()
        for k in range(3):
            day = today - timedelta(days=k)
            for hazard, score, band in (("heat", 72.0, "high"), ("flood", 35.0, "moderate"), ("air", 55.0, "moderate")):
                db.add(
                    RiskScore(
                        district_id="PUNE",
                        day=day,
                        hazard=hazard,
                        score=score,
                        band=band,
                        detail=json_driver(hazard),
                    )
                )
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(RiskScore).filter(RiskScore.district_id == "PUNE").delete()
        db.commit()


def json_driver(hazard):
    import json

    return json.dumps({"test_driver": hazard})


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_districts_seeded(client):
    r = client.get("/api/districts")
    assert r.status_code == 200
    ids = [d["id"] for d in r.json()]
    assert "PUNE" in ids and "WAYANAD" in ids


def test_resolve(client):
    assert client.get("/api/resolve", params={"name": "पुणे"}).json()["id"] == "PUNE"
    assert client.get("/api/resolve", params={"name": "wayanad"}).json()["id"] == "WAYANAD"


def test_risk_map(client, seeded_pune_risks):
    r = client.get("/api/risk-map")
    assert r.status_code == 200
    rows = {x["id"]: x for x in r.json()}
    assert "PUNE" in rows
    pune = rows["PUNE"]
    assert pune["overall"] >= 70
    assert pune["hazards"]["heat"]["band"] == "high"


def test_advisory_endpoint(client, seeded_pune_risks):
    r = client.get("/api/district/PUNE/advisory?lang=hi")
    assert r.status_code == 200
    body = r.json()
    assert "सुरक्षा सलाह" in body["text"]


def test_chat_endpoint(client):
    r = client.post("/api/chat", json={"session_id": "tc1", "message": "Pune advisory"})
    assert r.status_code == 200
    assert "Pune" in r.json()["reply"]


def test_webhook_verification(client):
    r = client.get(
        "/webhook/whatsapp",
        params={"mode": "subscribe", "token": "suraksha-verify", "challenge": "ABC123"},
    )
    assert r.status_code == 200
    assert r.text == "ABC123"
    assert client.get("/webhook/whatsapp", params={"mode": "subscribe", "token": "wrong", "challenge": "x"}).status_code == 403


def test_district_404(client):
    assert client.get("/api/district/NOPE").status_code == 404


def test_dashboard_served(client):
    assert client.get("/").status_code == 200
    assert "Suraksha" in client.get("/").text
