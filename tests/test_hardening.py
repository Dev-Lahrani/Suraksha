"""Regression tests for the security/reliability audit fixes."""

import asyncio
import hashlib
import hmac
import json
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from suraksha.config import get_settings
from suraksha.db import AlertLog, SessionLocal, Subscriber
from suraksha.delivery import alerts, whatsapp
from suraksha.ml import runner
from suraksha.server import app as app_module
from suraksha.server import ratelimit
from suraksha.server.app import app


@pytest.fixture()
def client():
    ratelimit.reset()
    with TestClient(app) as c:
        yield c


def test_web_chat_cannot_target_a_phone_number(client, monkeypatch):
    """A browser-supplied session id is namespaced, so it never becomes a phone number."""
    r = client.post("/api/chat", json={"session_id": "919876543210", "message": "subscribe Pune"})
    assert r.status_code == 200 and "WhatsApp" in r.json()["reply"]
    with SessionLocal() as db:
        assert db.get(Subscriber, "919876543210") is None
        assert db.get(Subscriber, "web:919876543210") is not None


def test_non_phone_recipients_are_never_sent_to(monkeypatch):
    monkeypatch.setattr(get_settings(), "whatsapp_token", "t")
    monkeypatch.setattr(get_settings(), "whatsapp_phone_number_id", "1")
    assert not whatsapp.is_whatsapp_id("web:919876543210")
    assert asyncio.run(whatsapp.send_text("web:919876543210", "hi")) is False
    assert whatsapp.is_whatsapp_id("919876543210")


def test_template_payload_strips_newlines(monkeypatch):
    sent = {}

    async def fake(to, payload):
        sent.update(payload)
        return True

    monkeypatch.setattr(whatsapp, "_send_payload", fake)
    asyncio.run(whatsapp.send_template("919876543210", "alert_v1", "en", ["a\n\nb\t c"]))
    assert sent["template"]["components"][0]["parameters"][0]["text"] == "a b c"


def test_failed_send_rolls_back_alert_log(monkeypatch):
    sid = "919000000077"
    alerts.subscribe(sid, "NAGPUR", "en")
    monkeypatch.setattr(alerts, "_high_risk_hazards", lambda *a, **k: [
        {"hazard": "heat", "score": 90.0, "band": "high", "detail": {}, "actions": [], "_day": alerts.india_today()}])
    monkeypatch.setattr(alerts, "detect_anomalies", lambda *a, **k: [])
    monkeypatch.setattr(alerts, "_deliver", AsyncMock(return_value=False))
    assert asyncio.run(alerts._alert_one(sid)) == []
    with SessionLocal() as db:
        assert db.query(AlertLog).filter_by(subscriber_id=sid).count() == 0
    monkeypatch.setattr(alerts, "_deliver", AsyncMock(return_value=True))
    assert len(asyncio.run(alerts._alert_one(sid))) == 1
    assert asyncio.run(alerts._alert_one(sid)) == []  # recorded, not re-sent


def test_dry_run_sends_nothing(monkeypatch):
    sid = "919000000078"
    alerts.subscribe(sid, "NAGPUR", "en")
    monkeypatch.setattr(alerts, "_high_risk_hazards", lambda *a, **k: [
        {"hazard": "heat", "score": 90.0, "band": "high", "detail": {}, "actions": [], "_day": alerts.india_today()}])
    monkeypatch.setattr(alerts, "detect_anomalies", lambda *a, **k: [])
    deliver = AsyncMock(return_value=True)
    monkeypatch.setattr(alerts, "_deliver", deliver)
    assert asyncio.run(alerts._alert_one(sid, dry_run=True))
    deliver.assert_not_called()


def test_model_payload_tamper_detected():
    payload = runner._dump_models({"a": 1})
    assert runner._load_models(payload) == {"a": 1}
    mac, _, body = payload.partition(".")
    with pytest.raises(ValueError):
        runner._load_models("0" * len(mac) + "." + body)
    with pytest.raises(ValueError):
        runner._load_models(runner.base64.b64encode(b"raw pickle").decode())  # legacy/unsigned


def test_admin_rejects_proxied_requests(client):
    r = client.post("/api/alerts/sweep", headers={"X-Forwarded-For": "203.0.113.9"})
    assert r.status_code == 403


def test_rate_limit(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "rate_limit_per_minute", 3)
    codes = [client.post("/api/chat", json={"message": "Pune"}).status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[3:] == [429, 429]


def test_health_hides_internal_errors(client):
    from suraksha.data import pipeline
    pipeline._pipeline_status["last_error"] = "GET https://secret.example failed"
    try:
        assert "secret.example" not in json.dumps(client.get("/api/health").json())
    finally:
        pipeline._pipeline_status["last_error"] = None


def test_webhook_dedupes_and_handles_batches(client, monkeypatch):
    app_module._seen_messages.clear()
    handled = []

    async def fake_handle(sid, text, language=None):
        handled.append((sid, text))
        return "ok"

    monkeypatch.setattr(app_module.brain, "handle_message", fake_handle)
    monkeypatch.setattr(app_module.whatsapp, "send_text", AsyncMock(return_value=True))
    msgs = [{"id": f"m{i}", "type": "text", "from": "919900000001", "text": {"body": f"Pune {i}"}} for i in (1, 2)]
    payload = {"entry": [{"changes": [{"value": {"messages": msgs}}]}]}
    assert client.post("/webhook/whatsapp", json=payload).json()["status"] == "ok"
    assert client.post("/webhook/whatsapp", json=payload).json()["status"] == "ignored"  # Meta retry
    assert len(handled) == 2


def test_district_ambiguity_and_precedence():
    from suraksha.agent.tools import find_district
    with SessionLocal() as db:
        assert find_district("Pune", db).id == "PUNE"
        assert find_district("weather in pune today", db).id == "PUNE"
        assert find_district("zzzz", db) is None


def test_missing_humidity_is_flagged():
    from suraksha.core.risks import heat_score
    assert heat_score(41, 33, None)["detail"]["humidity_assumed"] is True
    assert "humidity_assumed" not in heat_score(41, 33, 40)["detail"]


def test_states_rollup(client):
    data = client.get("/api/states").json()
    assert data["states"] and all(
        s["high"] + s["moderate"] + s["low"] + s["unknown"] == s["districts"] for s in data["states"])


# ---------------------------- Web Push ----------------------------

def _enable_push(monkeypatch):
    from suraksha.delivery.webpush import generate_keys
    private, public = generate_keys()
    monkeypatch.setattr(get_settings(), "vapid_private_key", private)
    monkeypatch.setattr(get_settings(), "vapid_public_key", public)
    return public


SUB = {"endpoint": "https://push.example.com/send/abc123", "district_id": "NAGPUR",
       "keys": {"p256dh": "B" * 20, "auth": "A" * 16}}


def test_push_disabled_without_keys(client):
    assert client.get("/api/push/key").json()["enabled"] is False
    assert client.post("/api/push/subscribe", json=SUB).status_code == 503


def test_push_subscribe_validates_and_roundtrips(client, monkeypatch):
    public = _enable_push(monkeypatch)
    assert client.get("/api/push/key").json()["public_key"] == public
    assert client.post("/api/push/subscribe", json={**SUB, "endpoint": "http://push.example.com/x"}).status_code == 422
    assert client.post("/api/push/subscribe", json={**SUB, "endpoint": "https://127.0.0.1/x"}).status_code == 422
    assert client.post("/api/push/subscribe", json={**SUB, "district_id": "NOPE"}).status_code == 404
    assert client.post("/api/push/subscribe", json=SUB).json()["status"] == "subscribed"
    assert client.post("/api/push/subscribe", json=SUB).status_code == 200  # idempotent upsert
    assert client.post("/api/push/unsubscribe", json={"endpoint": SUB["endpoint"]}).status_code == 200
    assert client.post("/api/push/unsubscribe", json={"endpoint": SUB["endpoint"]}).status_code == 404


def test_push_sweep_delivers_logs_and_prunes_expired(client, monkeypatch):
    from suraksha.db import PushSubscription
    _enable_push(monkeypatch)
    client.post("/api/push/subscribe", json=SUB)
    monkeypatch.setattr(alerts, "_high_risk_hazards", lambda *a, **k: [
        {"hazard": "heat", "score": 90.0, "band": "high", "detail": {}, "actions": [], "_day": alerts.india_today()}])
    monkeypatch.setattr(alerts, "detect_anomalies", lambda *a, **k: [])
    from suraksha.delivery import webpush
    send = AsyncMock(return_value="ok")
    monkeypatch.setattr(webpush, "send", send)
    assert asyncio.run(alerts.sweep_push())["push_alerted"] == 1
    assert asyncio.run(alerts.sweep_push())["push_alerted"] == 0  # deduped
    send.assert_awaited_once()
    with SessionLocal() as db:
        db.query(AlertLog).filter(AlertLog.subscriber_id.like("push:%")).delete(synchronize_session=False)
        db.commit()
    monkeypatch.setattr(webpush, "send", AsyncMock(return_value="gone"))
    asyncio.run(alerts.sweep_push())
    with SessionLocal() as db:
        assert db.query(PushSubscription).count() == 0
