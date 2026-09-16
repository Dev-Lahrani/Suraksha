"""Agent tools: typed functions the LLM can call (also used directly by the API)."""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from suraksha.agent.i18n import detect_language, format_advisory, format_forecast
from suraksha.core.anomaly import detect_anomalies
from suraksha.data.pipeline import latest_pm25
from suraksha.db import District, RiskScore, SessionLocal, WeatherDay
from datetime import date, timedelta


def find_district(query: str, db: Session) -> District | None:
    """Match a district by exact id, exact name (any language) or substring."""
    q = (query or "").strip().lower()
    if not q:
        return None
    districts = db.query(District).all()
    for d in districts:  # exact id
        if d.id.lower() == q:
            return d
    for d in districts:  # exact localized name
        for nm in (d.name_en, d.name_hi, d.name_mr):
            if nm and nm.lower() == q:
                return d
    for d in districts:  # substring / alias / light inflection match (Indic)
        for nm in (d.name_en, d.name_hi, d.name_mr):
            if not nm:
                continue
            low = nm.lower()
            if q in low or low in q:
                return d
            stem = nm[:-1]  # 'पुण्यात' should still find 'पुणे'
            if len(stem) >= 3 and stem in (query or ""):
                return d
    return None


def district_context(district_id: str) -> dict:
    """Everything the advisor needs about a district: risks, obs, forecast, anomalies."""
    with SessionLocal() as db:
        d = db.get(District, district_id)
        if d is None:
            return {}
        today = date.today()
        risks = (
            db.query(RiskScore)
            .filter(
                RiskScore.district_id == district_id,
                RiskScore.day >= today - timedelta(days=1),
                RiskScore.day <= today + timedelta(days=6),
            )
            .order_by(RiskScore.day)
            .all()
        )
        by_day: dict[date, dict] = {}
        for r in risks:
            detail = {}
            try:
                detail = json.loads(r.detail or "{}")
            except json.JSONDecodeError:
                pass
            by_day.setdefault(r.day, {})[r.hazard] = {
                "score": r.score,
                "band": r.band,
                "detail": detail,
            }
        obs = (
            db.query(WeatherDay)
            .filter(
                WeatherDay.district_id == district_id,
                WeatherDay.day >= today - timedelta(days=5),
                WeatherDay.day < today,
            )
            .order_by(WeatherDay.day)
            .all()
        )
        fc = (
            db.query(WeatherDay)
            .filter(
                WeatherDay.district_id == district_id,
                WeatherDay.day >= today,
                WeatherDay.day <= today + timedelta(days=6),
            )
            .order_by(WeatherDay.day)
            .all()
        )
        return {
            "district": {
                "id": d.id,
                "name_en": d.name_en,
                "name_hi": d.name_hi,
                "name_mr": d.name_mr,
                "state": d.state,
                "population": d.population,
                "lat": d.lat,
                "lon": d.lon,
            },
            "latest_pm25": latest_pm25(district_id),
            "observations": [
                {
                    "day": w.day.isoformat(),
                    "tavg": w.tavg,
                    "tmax": w.tmax,
                    "precipitation": w.precipitation,
                    "humidity": w.humidity,
                }
                for w in obs
            ],
            "forecast": [
                {
                    "day": w.day.isoformat(),
                    "tavg": w.tavg,
                    "tmax": w.tmax,
                    "precipitation": w.precipitation,
                }
                for w in fc
            ],
            "risks": {
                day.isoformat(): hazards
                for day, hazards in sorted(by_day.items())
            },
            "anomalies": detect_anomalies(district_id, lookback_days=7),
        }


def build_hazard_list(ctx: dict, language: str) -> list[dict]:
    """Attach playbook actions to the max-severity hazards for advisory building."""
    today = date.today().isoformat()
    hazards: dict[str, dict] = {}
    for day, hs in ctx.get("risks", {}).items():
        for hazard, res in hs.items():
            cur = hazards.get(hazard)
            if cur is None or (res.get("score") or 0) > (cur.get("score") or 0):
                merged = {"hazard": hazard, **res}
                merged["detail"] = dict(res.get("detail") or {})
                if day > today:  # surface which day drives it
                    merged["detail"]["peak_day"] = day
                hazards[hazard] = merged
    out = []
    for hazard, h in hazards.items():
        from suraksha.agent.i18n import playbook_actions

        h["actions"] = playbook_actions(hazard, h.get("band", "unknown"), language)
        out.append(h)
    order = {"high": 0, "moderate": 1, "low": 2, "unknown": 3}
    out.sort(key=lambda h: order.get(h.get("band", "unknown"), 3), reverse=False)
    return out


def advisory_text(district_id: str, language: str | None = None) -> tuple[str, str]:
    """Grounded advisory text + detected language (deterministic, no LLM needed)."""
    ctx = district_context(district_id)
    lang = language or detect_language(ctx.get("district", {}).get("name_en", ""), "en")
    hazards = build_hazard_list(ctx, lang)
    text = format_advisory(ctx["district"], hazards, lang)
    return text, lang


def forecast_text(district_id: str, language: str | None = None) -> str:
    ctx = district_context(district_id)
    lang = language or "en"
    return format_forecast(ctx["district"], ctx.get("forecast", []), lang)


def anomaly_text(district_id: str, language: str | None = None) -> str:
    """Human-readable anomaly bulletins (English payloads; agent can translate)."""
    ctx = district_context(district_id)
    events = ctx.get("anomalies", [])
    if not events:
        return "No anomalies vs 30-year climatology in the last 7 days."
    return "\n".join(f"⚠️ [{e['kind']}] {e['message']} ({e['day']})" for e in events)


def tool_schema() -> list[dict]:
    """OpenAI-style tool definitions advertised to the LLM."""
    return [
        {
            "type": "function",
            "function": {
                "name": "get_advisory",
                "description": "Get the full multilingual climate-risk advisory for a district.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "district_id": {"type": "string"},
                        "language": {"type": "string", "enum": ["en", "hi", "mr"]},
                    },
                    "required": ["district_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_forecast",
                "description": "Get the 7-day weather forecast summary for a district.",
                "parameters": {
                    "type": "object",
                    "properties": {"district_id": {"type": "string"}},
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_anomalies",
                "description": "Get climate anomalies vs 30-year climatology for a district.",
                "parameters": {
                    "type": "object",
                    "properties": {"district_id": {"type": "string"}},
                },
            },
        },
    ]
