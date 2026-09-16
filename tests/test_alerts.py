"""Proactive alerting tests (offline; no WhatsApp credentials → sends are skipped, not sent)."""

import asyncio
from datetime import date, timedelta

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from suraksha.agent.brain import handle_message
from suraksha.agent.i18n import format_alert
from suraksha.core.climatology import compute_climatology
from suraksha.db import AlertLog, Climatology, RiskScore, SessionLocal, Subscriber, WeatherDay
from suraksha.delivery.alerts import _alert_one, subscribe, sweep_subscribers, unsubscribe
from suraksha.server.app import app


def _seed_climatology():
    """Flat 30-year Pune-like climatology (same trick as test_anomaly)."""
    rows = []
    start = date(2024, 1, 1)
    for i in range(365 * 30):
        d = start + timedelta(days=i)
        rows.append({"day": d.isoformat(), "tavg": 26.0, "precipitation": 0.5})
    compute_climatology("NAGPUR", pd.DataFrame(rows))


def _clean(district_id="NAGPUR"):
    with SessionLocal() as db:
        db.query(WeatherDay).filter(WeatherDay.district_id == district_id).delete()
        db.query(RiskScore).filter(RiskScore.district_id == district_id).delete()
        db.query(Climatology).filter(Climatology.district_id == district_id).delete()
        db.query(Subscriber).delete()
        db.query(AlertLog).delete()
        db.commit()


@pytest.fixture()
def fresh_nagpur():
    _clean()
    yield
    _clean()


def _seed_high_flood_risk(district_id="NAGPUR", day=None):
    day = day or (date.today() + timedelta(days=1))
    with SessionLocal() as db:
        db.add(
            RiskScore(
                district_id=district_id,
                day=day,
                hazard="flood",
                score=78.0,
                band="high",
                detail='{"rain_3day_mm": 120.0}',
            )
        )
        db.commit()
    return day


def run(coro):
    return asyncio.run(coro)


# --------------------------- chat intents ---------------------------

async def test_subscribe_flow_via_chat(fresh_nagpur):
    reply = await handle_message("sub1", "subscribe Nagpur")
    assert "Subscribed" in reply
    with SessionLocal() as db:
        s = db.get(Subscriber, "sub1")
        assert s is not None and s.active and s.district_id == "NAGPUR"


async def test_stop_flow_via_chat(fresh_nagpur):
    await handle_message("sub2", "subscribe Nagpur")
    reply = await handle_message("sub2", "stop")
    assert "unsubscribed" in reply.lower()
    with SessionLocal() as db:
        s = db.get(Subscriber, "sub2")
        assert s is not None and not s.active


async def test_unsubscribe_helper(fresh_nagpur):
    assert unsubscribe("nobody") is False
    subscribe("sub2b", "NAGPUR", "en")
    assert unsubscribe("sub2b") is True
    assert unsubscribe("sub2b") is False  # already inactive


async def test_hindi_subscribe_confirms_in_hindi(fresh_nagpur):
    reply = await handle_message("sub3", "सदस्यता नागपुर")
    assert "सदस्यता" in reply and "STOP" in reply


async def test_bare_stop_does_not_crash_when_not_subscribed(fresh_nagpur):
    reply = await handle_message("sub4", "stop")
    assert "unsubscribed" in reply.lower()


async def test_normal_advisory_question_is_not_treated_as_command(fresh_nagpur):
    reply = await handle_message("sub5", "Pune advisory")
    assert "Pune" in reply  # advisory, not a stop confirmation


# --------------------------- sweep / dedupe ---------------------------

def test_sweep_without_whatsapp_is_a_noop(fresh_nagpur):
    subscribe("sw1", "NAGPUR", "en")
    _seed_high_flood_risk()
    summary = run(sweep_subscribers())
    assert summary["subscribers"] == 1
    assert summary["alerted"] == 0
    assert summary["skipped"] == 1  # WhatsApp not configured → skipped, not alerted
    with SessionLocal() as db:
        assert db.query(AlertLog).count() == 0  # nothing marked as sent


def test_alert_one_dedupes_exact_day_and_reason(fresh_nagpur):
    subscribe("sw2", "NAGPUR", "en")
    day = _seed_high_flood_risk()

    # Simulate a successful prior send for this exact (day, reason).
    with SessionLocal() as db:
        db.add(
            AlertLog(
                subscriber_id="sw2",
                district_id="NAGPUR",
                day=day,
                reason="high_risk:flood",
                channel="whatsapp",
                sent_at="2026-01-01T00:00:00+00:00",
            )
        )
        db.commit()

    assert run(_alert_one("sw2")) == []  # deduped, nothing new


def test_alert_one_suppresses_recent_same_reason(fresh_nagpur):
    """A hazard that stays high for days must not re-alert within DEDUPE_DAYS."""
    subscribe("sw3", "NAGPUR", "en")
    yesterday = date.today() - timedelta(days=1)
    with SessionLocal() as db:
        db.add(
            AlertLog(
                subscriber_id="sw3",
                district_id="NAGPUR",
                day=yesterday,
                reason="high_risk:flood",
                channel="whatsapp",
                sent_at=yesterday.isoformat(),
            )
        )
        db.commit()

    _seed_high_flood_risk()  # flood high again today/tomorrow
    assert run(_alert_one("sw3")) == []  # suppressed by the recent-same-reason rule


def test_format_alert_is_grounded_and_compact(fresh_nagpur):
    text = format_alert(
        {"name_en": "Nagpur", "name_hi": "नागपुर", "name_mr": "नागपूर", "state": "Maharashtra"},
        [
            {
                "hazard": "flood",
                "score": 78.0,
                "band": "high",
                "detail": {"peak_day": "2026-09-17"},
                "actions": ["Move to higher ground"],
            }
        ],
        [{"kind": "extreme_rain", "message": "Daily rainfall 90mm is 5.0x the 30-year normal"}],
        "en",
    )
    assert "🚨" in text and "Nagpur" in text
    assert "78/100" in text
    assert "peak 2026-09-17" in text
    assert "Move to higher ground" in text
    assert "5.0x the 30-year normal" in text
    assert "Sources" in text  # every alert keeps its citations


def test_format_alert_in_hindi(fresh_nagpur):
    text = format_alert(
        {"name_en": "Nagpur", "name_hi": "नागपुर", "name_mr": "नागपूर", "state": "Maharashtra"},
        [{"hazard": "flood", "score": 78.0, "band": "high", "detail": {}, "actions": ["ऊँची जगह जाएँ"]}],
        [],
        "hi",
    )
    assert "सुरक्षा अलर्ट" in text and "नागपुर" in text
    assert "ऊँची जगह जाएँ" in text


# --------------------------- API endpoints ---------------------------

def test_subscriber_api_roundtrip(fresh_nagpur):
    with TestClient(app) as client:
        r = client.post(
            "/api/subscribers",
            json={"id": "api1", "district_id": "NAGPUR", "language": "hi"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "subscribed"

        r = client.get("/api/subscribers/api1")
        assert r.status_code == 200
        assert r.json()["district"] == "Nagpur"
        assert r.json()["language"] == "hi"

        r = client.delete("/api/subscribers/api1")
        assert r.status_code == 200
        # Soft delete: row remains but is inactive (flag surfaces via header).
        r = client.get("/api/subscribers/api1")
        assert r.status_code == 200 and r.json()["active"] is False
        assert r.headers["X-Subscription-Active"] == "0"
        assert client.delete("/api/subscribers/api1").status_code == 404
        # Hard delete removes the row entirely.
        client.post("/api/subscribers", json={"id": "api1", "district_id": "NAGPUR"})
        assert client.delete("/api/subscribers/api1/hard").status_code == 200
        assert client.get("/api/subscribers/api1").status_code == 404


def test_subscriber_api_rejects_unknown_district(fresh_nagpur):
    with TestClient(app) as client:
        r = client.post("/api/subscribers", json={"id": "api2", "district_id": "ATLANTIS"})
        assert r.status_code == 400


def test_subscriber_api_rejects_missing_fields(fresh_nagpur):
    with TestClient(app) as client:
        assert client.post("/api/subscribers", json={"district_id": "NAGPUR"}).status_code == 400
        assert client.post("/api/subscribers", json={"id": "api3"}).status_code == 400


def test_sweep_endpoint_runs(fresh_nagpur):
    subscribe("api4", "NAGPUR", "en")
    with TestClient(app) as client:
        r = client.post("/api/alerts/sweep")
        assert r.status_code == 200
        assert r.json()["subscribers"] >= 1
