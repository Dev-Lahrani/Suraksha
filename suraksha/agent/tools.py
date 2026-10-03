"""Agent tools: typed functions the LLM can call (also used directly by the API)."""

from __future__ import annotations

import json
import re

from sqlalchemy.orm import Session

from suraksha.agent.i18n import DISTRICT_ALIASES, LANGUAGES, detect_language, format_advisory, format_forecast
from suraksha.core.anomaly import detect_anomalies
from suraksha.data.pipeline import latest_pm25
from suraksha.db import District, RiskScore, SessionLocal, WeatherDay
from datetime import date, timedelta


def find_district(query: str, db: Session) -> District | None:
    """Match a district by exact id, exact name (any language) or substring."""
    q = (query or "").strip().lower()
    if not q:
        return None
    for aliases in DISTRICT_ALIASES.values():
        for alias, district_id in aliases.items():
            if alias in q:
                return db.get(District, district_id)
    districts = db.query(District).all()
    for d in districts:  # exact id
        if d.id.lower() == q:
            return d
    for d in districts:  # exact localized name
        for nm in (d.name_en, d.name_hi, d.name_mr, d.name_ta, d.name_te, d.name_kn, d.name_bn):
            if nm and nm.lower() == q:
                return d
    if len(q) < 3:
        return None
    for d in districts:  # substring / alias / light inflection match (Indic)
        for nm in (d.name_en, d.name_hi, d.name_mr, d.name_ta, d.name_te, d.name_kn, d.name_bn):
            if not nm:
                continue
            low = nm.lower()
            if q in low or (low in q and (not low.isascii() or
                    re.search(r"(?<!\w)" + re.escape(low) + r"(?!\w)", q))):
                return d
            stem = nm[:-1]  # 'पुण्यात' should still find 'पुणे'
            if not nm.isascii() and len(stem) >= 3 and stem in (query or ""):
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
                "name_ta": d.name_ta,
                "name_te": d.name_te,
                "name_kn": d.name_kn,
                "name_bn": d.name_bn,
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
        if day < today:
            continue  # yesterday's hazard must not drive a forward-looking advisory
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
    if not ctx:
        raise ValueError(f"Unknown district {district_id}")
    hazards = build_hazard_list(ctx, lang)
    text = format_advisory(ctx["district"], hazards, lang)
    return text, lang


def forecast_text(district_id: str, language: str | None = None) -> str:
    ctx = district_context(district_id)
    lang = language or "en"
    if not ctx:
        raise ValueError(f"Unknown district {district_id}")
    return format_forecast(ctx["district"], ctx.get("forecast", []), lang)


def anomaly_text(district_id: str, language: str | None = None) -> str:
    """Human-readable anomaly bulletins (English payloads; agent can translate)."""
    ctx = district_context(district_id)
    events = ctx.get("anomalies", [])
    if not events:
        return "No anomalies vs 30-year climatology in the last 7 days."
    return "\n".join(f"⚠️ [{e['kind']}] {e['message']} ({e['day']})" for e in events)


def _hazard_reason(hazard: str, detail: dict) -> str:
    """One traceable line explaining the score, built from the engine's drivers."""
    if hazard == "heat":
        hi = detail.get("heat_index_c")
        tmax = detail.get("tmax_c")
        if hi is not None:
            return f"Heat index {hi}°C (T-max {tmax}°C)"
    elif hazard == "flood":
        r3 = detail.get("rain_3day_mm")
        p90 = detail.get("heavy_day_p90_mm")
        if r3 is not None:
            return f"3-day rain {r3}mm vs heavy-day p90 {p90}mm"
    elif hazard == "air":
        pm = detail.get("pm25_ugm3")
        aqi = detail.get("aqi_us_epa")
        if pm is not None:
            return f"PM2.5 {pm} µg/m³ (US-EPA AQI {aqi})"
    return "Drivers unavailable" if detail else "No driver detail recorded"


def watchlist(
    limit: int = 10,
    hazard: str | None = None,
    days_ahead: int = 2,
) -> list[dict]:
    """Districts ranked by worst expected hazard score in the next `days_ahead` days.

    The official-facing "where do we act first" view: each row carries the
    driving hazard, its score/band, and a one-line reason traceable to the
    risk-engine drivers (clarity criterion). Districts with no scored rows in
    the window are omitted — an absent district means "no data", never "safe".
    """
    if hazard not in (None, "all", "heat", "flood", "air"):
        raise ValueError(f"unknown hazard '{hazard}'")
    today = date.today()
    window_end = today + timedelta(days=max(0, days_ahead))
    with SessionLocal() as db:
        q = db.query(RiskScore).filter(
            RiskScore.day >= today,
            RiskScore.day <= window_end,
        )
        if hazard and hazard != "all":
            q = q.filter(RiskScore.hazard == hazard)
        rows = q.all()
        if not rows:
            return []
        districts = {d.id: d for d in db.query(District).all()}

    # Per district, keep the max-score row per hazard (peak day matters more
    # than the exact day it happens on — same rule as the alert sweep).
    per_district: dict[str, dict[str, tuple[float, str, dict, str]]] = {}
    for r in rows:
        try:
            detail = json.loads(r.detail or "{}")
        except json.JSONDecodeError:
            detail = {}
        if r.score is None:
            continue
        score = r.score
        cur = per_district.setdefault(r.district_id, {}).get(r.hazard)
        if cur is None or score > cur[0]:
            per_district[r.district_id][r.hazard] = (
                score,
                r.band or "unknown",
                detail,
                r.day.isoformat(),
            )

    out: list[dict] = []
    for did, hazards in per_district.items():
        d = districts.get(did)
        if d is None:
            continue
        top_hazard, (top_score, top_band, top_detail, peak_day) = max(
            hazards.items(), key=lambda kv: kv[1][0]
        )
        out.append(
            {
                "id": did,
                "name_en": d.name_en,
                "name_hi": d.name_hi,
                "name_mr": d.name_mr,
                "name_ta": d.name_ta,
                "name_te": d.name_te,
                "name_kn": d.name_kn,
                "name_bn": d.name_bn,
                "state": d.state,
                "lat": d.lat,
                "lon": d.lon,
                "population": d.population,
                "overall": round(top_score, 1) if top_score >= 0 else None,
                "band": top_band,
                "top_hazard": top_hazard,
                "peak_day": peak_day,
                "reason": _hazard_reason(top_hazard, top_detail),
                "hazards": {
                    h: {"score": round(v[0], 1) if v[0] >= 0 else None, "band": v[1]}
                    for h, v in hazards.items()
                },
            }
        )
    out.sort(key=lambda r: r["overall"] if r["overall"] is not None else -1.0, reverse=True)
    return out[: max(1, limit)]


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
                        "language": {"type": "string", "enum": list(LANGUAGES)},
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
