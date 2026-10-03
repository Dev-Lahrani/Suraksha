"""Decision-support briefings and an educational what-if lab."""

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ConfigDict

from suraksha.agent.i18n import LANGUAGES, playbook_actions
from suraksha.agent.tools import advisory_text, district_context, _hazard_reason
from suraksha.config import get_settings
from suraksha.core.risks import compute_risk_for_day

router = APIRouter(prefix="/api")


def mission_brief(district_id: str, language: str = "en") -> dict:
    if language not in LANGUAGES:
        raise HTTPException(422, "Unsupported language")
    context = district_context(district_id)
    if not context:
        raise HTTPException(404, "Unknown district")
    today = date.today()
    timeline, peaks = [], {}
    for offset in range(7):
        day = (today + timedelta(days=offset)).isoformat()
        hazards = context["risks"].get(day, {})
        known = {h: res for h, res in hazards.items() if res.get("score") is not None}
        timeline.append({"day": day, "hazards": hazards, "overall": max((r["score"] for r in known.values()), default=None),
                         "known_hazards": len(known), "missing_hazards": [h for h in ("heat", "flood", "air") if h not in known]})
        for hazard, result in known.items():
            if hazard not in peaks or result["score"] > peaks[hazard]["score"]:
                peaks[hazard] = {"hazard": hazard, "day": day, **result}
    actions = []
    for hazard, peak in sorted(peaks.items(), key=lambda item: item[1]["score"], reverse=True):
        actions.append({"hazard": hazard, "band": peak["band"], "score": peak["score"], "peak_day": peak["day"],
                        "reason": _hazard_reason(hazard, peak.get("detail") or {}),
                        "steps": playbook_actions(hazard, peak["band"], language)})
    scored_slots = sum(row["known_hazards"] for row in timeline)
    text, _ = advisory_text(district_id, language)
    return {"district": context["district"], "language": language, "demo": get_settings().demo_mode,
            "generated_at": datetime.now(timezone.utc).isoformat(), "advisory": text,
            "timeline": timeline, "priorities": actions,
            "coverage": {"scored_hazard_days": scored_slots, "possible_hazard_days": 21,
                         "percent": round(scored_slots / 21 * 100), "forecast_days": len(context["forecast"])},
            "anomalies": context["anomalies"],
            "limitations": ["Rainfall-based flood proxy, not hydrological routing.",
                            "No score means unknown, not safe.", "Coverage is availability, not accuracy or confidence.",
                            "Follow official local warnings; this is decision support, not an evacuation order."]}


@router.get("/district/{district_id}/mission")
def mission(district_id: str, lang: str = "en") -> dict:
    return mission_brief(district_id, lang)


class ScenarioInput(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")
    tmax: float = Field(38, ge=-20, le=60)
    humidity: float = Field(60, ge=0, le=100)
    rain_today: float = Field(0, ge=0, le=1000)
    rain_3day: float = Field(0, ge=0, le=3000)
    rain_p90: float = Field(30, gt=0, le=500)
    pm25: float | None = Field(None, ge=0, le=1000)
    language: str = "en"


@router.post("/scenario")
def scenario(body: ScenarioInput) -> dict:
    if body.language not in LANGUAGES:
        raise HTTPException(422, "Unsupported language")
    if body.rain_3day < body.rain_today:
        raise HTTPException(422, "3-day rainfall must include today's rainfall")
    risks = compute_risk_for_day(tmax=body.tmax, tavg=None, humidity=body.humidity,
                                 precipitation=body.rain_today, rain_3day=body.rain_3day,
                                 rain_p90=body.rain_p90, pm25=body.pm25)
    for hazard, result in risks.items():
        result["actions"] = playbook_actions(hazard, result["band"], body.language) if result["score"] is not None else []
    return {"simulation": True, "persisted": False, "inputs": body.model_dump(), "risks": risks,
            "note": "Educational what-if simulation, not a forecast. Uses the same deterministic engines; no database writes."}
