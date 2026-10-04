"""Watchlist endpoint + ranking logic tests (offline; seeded RiskScore rows)."""

from suraksha.core.clock import india_today
from datetime import date, timedelta
import json

import pytest
from fastapi.testclient import TestClient

from suraksha.agent.tools import watchlist
from suraksha.db import RiskScore, SessionLocal
from suraksha.server.app import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


DISTRICTS = ("PUNE", "DELHI_NW", "MUMBAI_SUB", "NAGPUR")


def _driver(hazard: str) -> str:
    """Realistic engine detail so `reason` strings have something to cite."""
    drivers = {
        "heat": {"heat_index_c": 47.5, "tmax_c": 42.0, "rh_pct": 55},
        "flood": {"rain_today_mm": 80.0, "rain_3day_mm": 210.0, "heavy_day_p90_mm": 45.0},
        "air": {"pm25_ugm3": 92.0, "aqi_us_epa": 169},
    }
    return json.dumps(drivers[hazard])


@pytest.fixture()
def seeded_watchlist():
    """DELHI_NW worst (heat 88), PUNE second (air 76), NAGPUR flood-only (45),
    MUMBAI_SUB heat rows only in the past (must be excluded from the window).

    Clears the whole risk_scores table first: earlier mocked-pipeline and
    integration tests ingest every registry district and leave future-dated
    rows behind (they only clean PUNE). This file runs last alphabetically
    and owns the table, so ranking assertions stay deterministic.
    """
    today = india_today()
    rows = [
        ("DELHI_NW", today, "heat", 88.0, "high"),
        ("DELHI_NW", today, "air", 40.0, "moderate"),
        ("PUNE", today + timedelta(days=1), "air", 76.0, "high"),
        ("NAGPUR", today, "flood", 45.0, "moderate"),
        ("MUMBAI_SUB", today - timedelta(days=2), "heat", 95.0, "high"),
    ]
    with SessionLocal() as db:
        db.query(RiskScore).delete()
        for did, day, hazard, score, band in rows:
            db.add(
                RiskScore(
                    district_id=did,
                    day=day,
                    hazard=hazard,
                    score=score,
                    band=band,
                    detail=_driver(hazard),
                )
            )
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(RiskScore).delete()
        db.commit()


def test_watchlist_orders_by_peak_score(seeded_watchlist):
    rows = watchlist()
    ids = [r["id"] for r in rows]
    assert ids[0] == "DELHI_NW"
    assert ids.index("PUNE") < ids.index("NAGPUR")
    # A district with rows only in the past is not "highest risk now"
    assert "MUMBAI_SUB" not in ids


def test_watchlist_reason_is_traceable(seeded_watchlist):
    top = watchlist()[0]
    assert top["top_hazard"] == "heat"
    assert top["band"] == "high"
    assert top["overall"] == 88.0
    assert "47.5" in top["reason"] and "42.0" in top["reason"]
    # peak day is surfaced for officials
    assert top["peak_day"] == india_today().isoformat()


def test_watchlist_hazard_filter(seeded_watchlist):
    rows = watchlist(hazard="flood")
    assert [r["id"] for r in rows] == ["NAGPUR"]
    assert rows[0]["top_hazard"] == "flood"
    assert "210.0" in rows[0]["reason"]


def test_watchlist_limit(seeded_watchlist):
    assert len(watchlist(limit=2)) == 2
    assert len(watchlist(limit=1)) == 1


def test_watchlist_multi_day_window_takes_peak(seeded_watchlist):
    rows = watchlist(days_ahead=1)
    pune = next(r for r in rows if r["id"] == "PUNE")
    # PUNE's air peak lives tomorrow — inside the window
    assert pune["overall"] == 76.0
    # DELHI_NW's rows are today — still included at days_ahead=1
    assert rows[0]["id"] == "DELHI_NW"


def test_watchlist_empty_when_no_data():
    """No scored rows in the window at all -> empty list, not an error.

    Clears every risk row: mocked-pipeline tests leave rows for other
    districts, and this file runs last alphabetically.
    """
    with SessionLocal() as db:
        db.query(RiskScore).delete()
        db.commit()
    assert watchlist() == []


def test_watchlist_rejects_unknown_hazard(seeded_watchlist):
    with pytest.raises(ValueError):
        watchlist(hazard="volcano")


def test_watchlist_endpoint(client, seeded_watchlist):
    r = client.get("/api/watchlist")
    assert r.status_code == 200
    rows = r.json()
    assert rows[0]["id"] == "DELHI_NW"
    assert rows[0]["reason"]
    assert {"heat": 88.0, "air": 40.0}.items() <= {k: v["score"] for k, v in rows[0]["hazards"].items()}.items()


def test_watchlist_endpoint_params(client, seeded_watchlist):
    assert client.get("/api/watchlist", params={"limit": 1}).json()[0]["id"] == "DELHI_NW"
    flood = client.get("/api/watchlist", params={"hazard": "flood"}).json()
    assert [r["id"] for r in flood] == ["NAGPUR"]
    assert client.get("/api/watchlist", params={"hazard": "lava"}).status_code == 422
    assert client.get("/api/watchlist", params={"limit": 0}).status_code == 422
