"""Finale-facing flows: mission briefing, simulations, installability and safety."""
import base64
import pickle
from suraksha.core.clock import india_today
from datetime import date, timedelta
from unittest.mock import AsyncMock

import httpx
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from suraksha.agent.brain import _subscription_command
from suraksha.agent.tools import build_hazard_list
from suraksha.config import get_settings
from suraksha.db import ModelRun, RiskScore, SessionLocal
from suraksha.server.app import app


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client


@pytest.fixture
def mission_data(clean_pune):
    with SessionLocal() as db:
        db.add_all([RiskScore(district_id="PUNE",day=india_today(),hazard="heat",score=70,band="high",detail='{"heat_index_c":50,"tmax_c":42}'),
                    RiskScore(district_id="PUNE",day=india_today()+timedelta(days=1),hazard="heat",score=85,band="high",detail='{"heat_index_c":56,"tmax_c":45}')])
        db.commit()


def test_mission_timeline_and_priorities(client,mission_data):
    response=client.get("/api/district/PUNE/mission?lang=hi")
    assert response.status_code==200
    data=response.json()
    assert len(data["timeline"])==7
    assert data["coverage"]["scored_hazard_days"]==2
    assert data["timeline"][2]["overall"] is None
    assert "air" in data["timeline"][0]["missing_hazards"]
    assert data["priorities"][0]["score"]==85
    assert data["priorities"][0]["steps"]
    assert client.get("/api/district/NOPE/mission").status_code==404
    assert client.get("/api/district/PUNE/mission?lang=invalid").status_code==422


def test_scenario_is_explainable_and_non_persistent(client,mission_data):
    with SessionLocal() as db:
        before=db.query(RiskScore).count()
    response=client.post("/api/scenario",json={"tmax":44,"humidity":65,"rain_today":110,"rain_3day":260,"rain_p90":35,"pm25":180})
    assert response.status_code==200
    data=response.json()
    assert data["simulation"] and not data["persisted"]
    assert data["risks"]["heat"]["band"]=="high"
    assert data["risks"]["flood"]["band"]=="high"
    assert data["risks"]["air"]["band"]=="high"
    assert "heat_index_c" in data["risks"]["heat"]["detail"]
    with SessionLocal() as db:
        assert db.query(RiskScore).count()==before
    assert client.post("/api/scenario",json={"rain_today":100,"rain_3day":1}).status_code==422
    assert client.post("/api/scenario",json={"humidity":101}).status_code==422
    assert client.post("/api/scenario",json={"tmax":20,"unexpected":True}).status_code==422
    assert client.post("/api/scenario",json={"language":"invalid"}).status_code==422


def test_scenario_unknown_air_stays_unknown(client):
    data=client.post("/api/scenario",json={}).json()
    assert data["risks"]["air"]["score"] is None
    assert data["risks"]["air"]["actions"]==[]


def test_pwa_assets_and_api_exclusion(client):
    manifest=client.get("/manifest.webmanifest")
    assert manifest.status_code==200 and manifest.json()["display"]=="standalone"
    worker=client.get("/sw.js")
    assert worker.status_code==200 and worker.headers["cache-control"]=="no-cache"
    assert 'url.pathname.startsWith("/api/")' in worker.text
    assert client.get("/icon.svg").status_code==200


def test_yesterday_does_not_drive_tomorrow_advisory():
    yesterday=(india_today()-timedelta(days=1)).isoformat()
    context={"risks":{yesterday:{"heat":{"score":99,"band":"high","detail":{}}},india_today().isoformat():{"heat":{"score":10,"band":"low","detail":{}}}}}
    assert build_hazard_list(context,"en")[0]["score"]==10


def test_stop_questions_are_not_unsubscribe_commands():
    assert _subscription_command("Will the rain stop in Pune?") is None
    assert _subscription_command("How do I subscribe?") is None
    assert _subscription_command("STOP")=="stop"
    assert _subscription_command("subscribe Pune")=="subscribe"


def test_null_scores_are_not_safe_on_map(client,clean_pune):
    with SessionLocal() as db:
        db.add(RiskScore(district_id="PUNE",day=india_today(),hazard="air",score=None,band="unknown"))
        db.commit()
    row=next(r for r in client.get("/api/risk-map").json() if r["id"]=="PUNE")
    assert row["overall"] is None


def test_subscriber_input_errors(client):
    assert client.post("/api/subscribers",json=[]).status_code==400
    assert client.post("/api/subscribers",content="{").status_code==400
    assert client.post("/api/subscribers",json={"id":"demo","district_id":"PUNE","language":"invalid"}).status_code==422


def test_doctor_local_only(capsys):
    from suraksha.cli import main
    assert main(["doctor"])==0
    assert "frontend_assets" in capsys.readouterr().out


async def test_bad_api_parameters_not_retried():
    from suraksha.data.open_meteo import _get_json
    client=AsyncMock()
    client.get.return_value=httpx.Response(400,request=httpx.Request("GET","https://example.test"))
    with pytest.raises(httpx.HTTPStatusError):
        await _get_json(client,"https://example.test",{})
    assert client.get.call_count==1


def test_ml_per_target_withholding(monkeypatch,clean_pune):
    from suraksha.ml import runner
    with SessionLocal() as db:
        db.query(ModelRun).filter_by(district_id="PUNE").delete()
        db.add(ModelRun(district_id="PUNE",trained_at="2026-10-03T00:00:00+00:00",payload=base64.b64encode(pickle.dumps({})).decode(),mae_tavg=1,mae_tavg_baseline=2,mae_rain=3,mae_rain_baseline=2))
        db.commit()
    monkeypatch.setattr(runner,"load_history",lambda _:pd.DataFrame([{"day":(india_today()-timedelta(days=1)).isoformat()}]))
    monkeypatch.setattr(runner,"climatology_map",lambda _: {})
    monkeypatch.setattr(runner,"predict",lambda *args,**kwargs:[{"day":india_today().isoformat(),"tavg":30,"precipitation":99}])
    rows=runner.ml_outlook("PUNE")
    assert rows[0]["tavg"]==30 and rows[0]["precipitation"] is None
    with SessionLocal() as db:
        db.query(ModelRun).filter_by(district_id="PUNE").delete()
        db.commit()


def test_isolated_first_launch_demo_end_to_end(tmp_path):
    import os
    import subprocess
    import sys
    code = '''
from fastapi.testclient import TestClient
from suraksha.server.app import app
with TestClient(app) as client:
    assert client.get('/api/health').json()['demo']
    assert len(client.get('/api/districts').json()) == 42
    watchlist = client.get('/api/watchlist').json()
    assert watchlist and watchlist[0]['overall'] >= 60
    district = watchlist[0]['id']
    mission = client.get(f'/api/district/{district}/mission').json()
    assert mission['demo'] and mission['priorities']
    assert client.get(f'/api/district/{district}/brief.pdf').content.startswith(b'%PDF')
    assert 'synthetic_demo' in client.get(f'/api/district/{district}/export.csv').text
    assert 'DEMO' in client.post('/api/chat', json={'message': district + ' advisory'}).json()['reply']
    assert len(client.get('/api/compare?ids=PUNE,NAGPUR').json()['districts']) == 2
    assert client.post('/api/scenario', json={}).json()['simulation']
    assert client.get('/sw.js').status_code == 200
    assert client.post('/api/ingest').status_code == 409
'''
    environment = dict(os.environ, DEMO_MODE="true", DATABASE_URL=f"sqlite:///{tmp_path / 'isolated-demo.db'}", INGEST_INTERVAL_MINUTES="0")
    result = subprocess.run([sys.executable, "-c", code], env=environment, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stderr


def test_api_headers(client):
    response = client.get("/api/health")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_demo_mode_labels_mission(client,mission_data,monkeypatch):
    monkeypatch.setattr(get_settings(),"demo_mode",True)
    assert client.get("/api/district/PUNE/mission").json()["demo"]
