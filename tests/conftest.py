"""Test configuration: offline, throwaway SQLite database."""

import os
import sys
from pathlib import Path

# Must run before any `suraksha` import: config → db engine read these.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["DATABASE_URL"] = "sqlite:///data/test_suraksha.db"
os.environ["NUGEN_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ["INGEST_INTERVAL_MINUTES"] = "0"
os.environ["WHATSAPP_TOKEN"] = ""
os.environ["WHATSAPP_PHONE_NUMBER_ID"] = ""
os.environ["WHATSAPP_APP_SECRET"] = ""
os.environ["ADMIN_API_KEY"] = ""
os.environ["DEMO_MODE"] = "false"
for language in ("EN", "HI", "MR", "TA", "TE", "KN", "BN", "GU", "PA", "ML", "UR"):
    os.environ[f"TTS_VOICE_{language}"] = ""

TEST_DB = ROOT / "data" / "test_suraksha.db"
if TEST_DB.exists():
    TEST_DB.unlink()

import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def database():
    from suraksha.db import init_db

    init_db()
    yield


@pytest.fixture()
def clean_pune():
    """Remove PUNE time-series rows so anomaly/brain tests are deterministic."""
    from suraksha.db import Climatology, RiskScore, SessionLocal, WeatherDay

    with SessionLocal() as db:
        db.query(WeatherDay).filter(WeatherDay.district_id == "PUNE").delete()
        db.query(RiskScore).filter(RiskScore.district_id == "PUNE").delete()
        db.query(Climatology).filter(Climatology.district_id == "PUNE").delete()
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(WeatherDay).filter(WeatherDay.district_id == "PUNE").delete()
        db.query(RiskScore).filter(RiskScore.district_id == "PUNE").delete()
        db.query(Climatology).filter(Climatology.district_id == "PUNE").delete()
        db.commit()
