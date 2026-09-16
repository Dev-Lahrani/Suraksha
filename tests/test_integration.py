"""PDF brief, ML forecaster integration and WhatsApp voice-note tests (offline).

Covers:
- PDF brief: renders for a seeded district and 404s for unknown ones.
- ML runner: validate-or-withhold persistence, outlook serving, throttle.
- Webhook: voice-note (audio) events trigger the voice-advisory flow.
"""

import base64
import json
import pickle
from datetime import date, timedelta
from unittest.mock import patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from suraksha.core.climatology import compute_climatology
from suraksha.db import ModelRun, RiskScore, SessionLocal, WeatherDay
from suraksha.delivery.whatsapp import extract_webhook_event
from suraksha.ml import runner as ml_runner
from suraksha.server.app import app


@pytest.fixture()
def api_client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def seeded_pune_risks():
    """A few recent PUNE risk rows (mirrors the fixture in test_app.py)."""
    with SessionLocal() as db:
        today = date.today()
        for k in range(3):
            day = today - timedelta(days=k)
            for hazard, score, band in (
                ("heat", 72.0, "high"),
                ("flood", 35.0, "moderate"),
                ("air", 55.0, "moderate"),
            ):
                db.add(
                    RiskScore(
                        district_id="PUNE",
                        day=day,
                        hazard=hazard,
                        score=score,
                        band=band,
                        detail=json.dumps({"seed": hazard}),
                    )
                )
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(RiskScore).filter(RiskScore.district_id == "PUNE").delete()
        db.commit()


# --------------------------- PDF brief ---------------------------


def test_pdf_brief_renders_for_seeded_district(seeded_pune_risks):
    from suraksha.delivery.pdf_brief import build_brief

    pdf = build_brief("PUNE")
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000


def test_pdf_brief_unknown_district_raises():
    from suraksha.delivery.pdf_brief import build_brief

    with pytest.raises(ValueError):
        build_brief("ATLANTIS")


def test_pdf_brief_endpoint(api_client, seeded_pune_risks):
    r = api_client.get("/api/district/PUNE/brief.pdf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    assert api_client.get("/api/district/NOPE/brief.pdf").status_code == 404


# --------------------------- ML runner ---------------------------


def _seed_history(district_id="PUNE", days=400):
    """Synthetic observed history + flat climatology (same trick as test_anomaly)."""
    rows = []
    start = date(2024, 1, 1)
    for i in range(365 * 30):
        d = start + timedelta(days=i)
        rows.append({"day": d.isoformat(), "tavg": 26.0, "precipitation": 0.5})
    compute_climatology(district_id, pd.DataFrame(rows))
    rng_days = [date.today() - timedelta(days=k) for k in range(days, 0, -1)]
    with SessionLocal() as db:
        for d in rng_days:
            db.add(
                WeatherDay(
                    district_id=district_id,
                    day=d,
                    tavg=26.0,
                    tmax=31.0,
                    tmin=21.0,
                    precipitation=0.5,
                    humidity=60.0,
                    wind=8.0,
                    is_forecast=False,
                )
            )
        db.commit()


def _clean_history(district_id="PUNE"):
    with SessionLocal() as db:
        db.query(WeatherDay).filter(WeatherDay.district_id == district_id).delete()
        db.query(RiskScore).filter(RiskScore.district_id == district_id).delete()
        db.query(ModelRun).filter(ModelRun.district_id == district_id).delete()
        db.commit()
    from suraksha.db import Climatology

    with SessionLocal() as db:
        db.query(Climatology).filter(Climatology.district_id == district_id).delete()
        db.commit()


@pytest.fixture()
def pune_history():
    _clean_history()
    _seed_history()
    yield
    _clean_history()


def test_load_history_shape(pune_history):
    hist = ml_runner.load_history("PUNE")
    assert hist is not None
    assert len(hist) == 400
    assert set(["day", "tavg", "precipitation", "humidity", "wind"]) <= set(hist.columns)


def test_load_history_too_short_returns_none(pune_history):
    with SessionLocal() as db:
        db.query(WeatherDay).filter(WeatherDay.district_id == "PUNE").delete()
        db.commit()
    assert ml_runner.load_history("PUNE") is None


def test_run_forecaster_stores_or_withholds(pune_history):
    """Constant weather may legitimately fail to beat the baseline — both
    outcomes must leave the system in a consistent state."""
    result = ml_runner.run_forecaster("PUNE")
    with SessionLocal() as db:
        run = db.get(ModelRun, "PUNE")
    if result:
        assert run is not None
        mae = json.loads(json.dumps({
            "t": run.mae_tavg, "tb": run.mae_tavg_baseline,
            "r": run.mae_rain, "rb": run.mae_rain_baseline,
        }))
        # validate-or-withhold: a stored model must beat its baseline somewhere
        assert mae["t"] < mae["tb"] or mae["r"] < mae["rb"]
    else:
        assert run is None


def test_ml_outlook_roundtrip(pune_history):
    if not ml_runner.run_forecaster("PUNE"):
        pytest.skip("model withheld on degenerate data — nothing to serve")
    rows = ml_runner.ml_outlook("PUNE", days=5)
    assert rows is not None and len(rows) == 5
    assert all("day" in r and "tavg" in r and "precipitation" in r for r in rows)
    assert all(r["precipitation"] >= 0 for r in rows)


def test_ml_outlook_absent_model_is_none(pune_history):
    assert ml_runner.ml_outlook("PUNE") is None


def test_model_summary_shape(pune_history):
    assert ml_runner.model_summary("PUNE") is None
    if ml_runner.run_forecaster("PUNE"):
        s = ml_runner.model_summary("PUNE")
        assert set(s) == {
            "trained_at", "mae_tavg", "mae_tavg_baseline", "mae_rain", "mae_rain_baseline"
        }


def test_pipeline_summary_includes_ml_field(clean_pune):
    """The pipeline must surface the ml_models field (0 is fine offline)."""
    import asyncio

    from suraksha.data import pipeline
    from tests.test_pipeline import FakeClient

    with patch.object(pipeline, "httpx") as mock_httpx:
        mock_httpx.AsyncClient = FakeClient
        summary = asyncio.run(pipeline.run_pipeline())
    assert "ml_models" in summary
    assert summary["ml_models"] >= 0


def test_ml_outlook_endpoint_contract(api_client, pune_history):
    r = api_client.get("/api/district/PUNE/ml-outlook")
    assert r.status_code == 200
    body = r.json()
    assert set(["available", "rows", "validation"]) <= set(body)
    if body["available"]:
        assert len(body["rows"]) == 5
        assert body["validation"]["mae_tavg"] is not None
    assert api_client.get("/api/district/NOPE/ml-outlook").status_code == 404


def test_pickle_roundtrip_of_models(pune_history):
    """The stored payload must deserialize back into a usable models dict."""
    if not ml_runner.run_forecaster("PUNE"):
        pytest.skip("model withheld on degenerate data")
    with SessionLocal() as db:
        run = db.get(ModelRun, "PUNE")
    models = pickle.loads(base64.b64decode(run.payload))
    assert "t_anom" in models and "precip" in models and "mae" in models


# --------------------- WhatsApp voice-note flow ---------------------


def _audio_payload(from_num="919900112233"):
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "type": "audio",
                                    "from": from_num,
                                    "timestamp": "1700000000",
                                    "audio": {"id": "media-1", "mime_type": "audio/ogg"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }


def test_extract_webhook_audio_event():
    event = extract_webhook_event(_audio_payload())
    assert event is not None
    assert event["type"] == "audio"
    assert event["from"] == "919900112233"


def test_voice_command_returns_advisory_text():
    """No WhatsApp credentials in tests → the fallback path returns the
    advisory text with an explicit voice-note line appended."""
    import asyncio

    from suraksha.agent.brain import handle_message

    reply = asyncio.run(handle_message("voice-t1", "voice Pune"))
    assert "Pune" in reply
    assert "voice note" in reply.lower()


def test_voice_command_unknown_district_asks_back():
    import asyncio

    from suraksha.agent.brain import handle_message

    reply = asyncio.run(handle_message("voice-t2", "ऑडियो"))
    # Hindi asks back with ज़िले (nukta), Marathi would use जिल्हा
    assert "district" in reply.lower() or "ज़िले" in reply or "जिल्हा" in reply


def test_voice_note_without_whatsapp_is_graceful():
    """End-to-end webhook: audio event must not crash and must return ok/ignored."""
    with TestClient(app) as c:
        r = c.post("/webhook/whatsapp", json=_audio_payload())
        assert r.status_code == 200
        assert r.json()["status"] in ("ok", "send-failed", "ignored")
