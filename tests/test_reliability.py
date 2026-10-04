"""Safety regressions: calendar consistency and honest data availability."""
from datetime import datetime, date, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from suraksha.core.clock import india_today
from suraksha.agent.tools import build_hazard_list
from suraksha.db import RiskScore, SessionLocal
from suraksha.server.app import app


def test_india_date_crosses_utc_midnight_early():
    assert india_today(datetime(2026, 10, 3, 18, 29, tzinfo=timezone.utc)) == date(2026, 10, 3)
    assert india_today(datetime(2026, 10, 3, 18, 30, tzinfo=timezone.utc)) == date(2026, 10, 4)
    with pytest.raises(ValueError, match="aware"):
        india_today(datetime(2026, 10, 3))


@pytest.mark.parametrize("unknown_first", [True, False])
def test_known_zero_beats_unknown(unknown_first):
    days = [india_today().isoformat(), (india_today() + timedelta(days=1)).isoformat()]
    unknown = {"score": None, "band": "unknown", "detail": {}}
    known = {"score": 0, "band": "low", "detail": {}}
    values = [unknown, known] if unknown_first else [known, unknown]
    result = build_hazard_list({"risks": {day: {"heat": value} for day, value in zip(days, values)}}, "en")
    assert len(result) == 1 and result[0]["score"] == 0 and result[0]["band"] == "low"
    assert build_hazard_list({"risks": {days[0]: {"heat": unknown}}}, "en") == []


def test_overview_per_hazard_coverage(clean_pune):
    selected = date(2040, 1, 1)
    with SessionLocal() as db:
        db.add_all([RiskScore(district_id="PUNE", day=selected, hazard="heat", score=0, band="low"),
                    RiskScore(district_id="PUNE", day=selected, hazard="air", score=None, band="unknown")])
        db.commit()
    with TestClient(app) as client:
        response = client.get("/api/overview", params={"day": selected.isoformat()})
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        data = response.json()
        assert data["covered"] == 1 and data["fully_covered"] == 0 and data["partial"] == 1
        assert data["hazard_coverage"]["heat"]["covered"] == 1
        assert "PUNE" not in data["hazard_coverage"]["heat"]["missing_district_ids"]
        assert "PUNE" in data["hazard_coverage"]["air"]["missing_district_ids"]
        assert data["hazard_coverage"]["air"]["unknown"] == data["districts"]


def test_api_defaults_follow_india_day(monkeypatch, clean_pune):
    import suraksha.server.app as server
    import suraksha.server.insights as insights
    selected = date(2040, 2, 1)
    monkeypatch.setattr(server, "india_today", lambda: selected)
    monkeypatch.setattr(insights, "india_today", lambda: selected)
    with SessionLocal() as db:
        db.add(RiskScore(district_id="PUNE", day=selected, hazard="heat", score=0, band="low"))
        db.commit()
    with TestClient(app) as client:
        assert client.get("/api/health").json()["time"] == selected.isoformat()
        assert client.get("/api/overview").json()["day"] == selected.isoformat()
        assert next(r for r in client.get("/api/risk-map").json() if r["id"] == "PUNE")["overall"] == 0
