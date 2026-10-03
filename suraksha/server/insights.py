"""Read-only command-center features. No credentials or external calls."""

import csv
import io
import math
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from suraksha.agent.i18n import language_catalog, playbook_actions
from suraksha.agent.tools import build_hazard_list, district_context
from suraksha.config import get_settings
from suraksha.db import District, RiskScore, WeatherDay, get_db

router = APIRouter(prefix="/api")


@router.get("/languages")
def languages() -> list[dict]:
    return language_catalog()


@router.get("/overview")
def overview(day: date | None = None, db: Session = Depends(get_db)) -> dict:
    selected = day or date.today()
    districts = db.query(District).all()
    risks = db.query(RiskScore).filter(RiskScore.day == selected, RiskScore.score.isnot(None)).all()
    scores: dict[str, float] = {}
    hazard_counts = {h: 0 for h in ("heat", "flood", "air")}
    for risk in risks:
        scores[risk.district_id] = max(scores.get(risk.district_id, 0), risk.score)
        if risk.score >= 60 and risk.hazard in hazard_counts:
            hazard_counts[risk.hazard] += 1
    high = {did for did, score in scores.items() if score >= 60}
    return {"day": selected.isoformat(), "demo": get_settings().demo_mode,
            "districts": len(districts), "covered": len(scores),
            "high": len(high), "moderate": sum(25 <= s < 60 for s in scores.values()),
            "low": sum(s < 25 for s in scores.values()), "unknown": len(districts) - len(scores),
            "population_in_high_risk_districts": sum(d.population or 0 for d in districts if d.id in high),
            "hazard_high_counts": hazard_counts,
            "note": "Population is district registry population, not estimated exposed people. Coverage means at least one scored hazard, not all hazards."}


def history_rows(db: Session, district_id: str, days: int) -> list[dict]:
    if db.get(District, district_id) is None:
        raise HTTPException(404, "Unknown district")
    start, end = date.today() - timedelta(days=days - 1), date.today() + timedelta(days=6)
    weather = db.query(WeatherDay).filter(WeatherDay.district_id == district_id,
                                        WeatherDay.day >= start, WeatherDay.day <= end).order_by(WeatherDay.day).all()
    risks = db.query(RiskScore).filter(RiskScore.district_id == district_id,
                                     RiskScore.day >= start, RiskScore.day <= end).all()
    rows = {w.day: {"day": w.day.isoformat(), "tavg": w.tavg, "tmax": w.tmax,
                    "precipitation": w.precipitation, "is_forecast": w.is_forecast, "risks": {}} for w in weather}
    for risk in risks:
        row = rows.setdefault(risk.day, {"day": risk.day.isoformat(), "tavg": None, "tmax": None,
                                        "precipitation": None, "is_forecast": risk.day >= date.today(), "risks": {}})
        row["risks"][risk.hazard] = {"score": risk.score, "band": risk.band}
    return [rows[day] for day in sorted(rows)]


@router.get("/district/{district_id}/history")
def history(district_id: str, days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db)) -> dict:
    return {"district_id": district_id, "demo": get_settings().demo_mode,
            "rows": history_rows(db, district_id, days)}


@router.get("/district/{district_id}/export.csv")
def export(district_id: str, days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db)) -> Response:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["day", "tavg_c", "tmax_c", "rain_mm", "is_forecast", "heat_score", "flood_score", "air_score", "synthetic_demo"])
    for row in history_rows(db, district_id, days):
        writer.writerow([row["day"], row["tavg"], row["tmax"], row["precipitation"], row["is_forecast"],
                         *(row["risks"].get(h, {}).get("score") for h in ("heat", "flood", "air")), get_settings().demo_mode])
    return Response(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{district_id}-climate.csv"'})


@router.get("/compare")
def compare(ids: str = Query(max_length=256), lang: str = "en") -> dict:
    district_ids = list(dict.fromkeys(part.strip() for part in ids.split(",") if part.strip()))
    if not 2 <= len(district_ids) <= 4:
        raise HTTPException(422, "Choose between 2 and 4 distinct districts")
    result = []
    for district_id in district_ids:
        ctx = district_context(district_id)
        if not ctx:
            raise HTTPException(404, f"Unknown district {district_id}")
        result.append({"district": ctx["district"], "hazards": build_hazard_list(ctx, lang),
                       "forecast": ctx["forecast"], "anomalies": ctx["anomalies"]})
    return {"demo": get_settings().demo_mode, "districts": result,
            "window": "Peak available scores in advisory window; not today's score alone"}


@router.get("/nearest")
def nearest(lat: float = Query(ge=-90, le=90), lon: float = Query(ge=-180, le=180), db: Session = Depends(get_db)) -> dict:
    districts = db.query(District).all()
    if not districts:
        raise HTTPException(404, "District registry empty")
    def distance(district):
        dlat, dlon = math.radians(district.lat - lat), math.radians(district.lon - lon)
        a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat)) * math.cos(math.radians(district.lat)) * math.sin(dlon / 2) ** 2
        return 6371 * 2 * math.asin(min(1, math.sqrt(a)))
    district = min(districts, key=distance)
    return {"id": district.id, "name_en": district.name_en, "state": district.state,
            "distance_km": round(distance(district), 1), "note": "Nearest curated district HQ, not an administrative boundary lookup."}


@router.get("/preparedness")
def preparedness(hazard: str = Query("heat", pattern="^(heat|flood|air)$"),
                 band: str = Query("high", pattern="^(low|moderate|high)$"), lang: str = "en") -> dict:
    return {"hazard": hazard, "band": band, "language": lang,
            "actions": [{"id": f"{hazard}-{band}-{index}", "text": action}
                        for index, action in enumerate(playbook_actions(hazard, band, lang))],
            "note": "Preparedness guidance, not official evacuation orders. Follow local authorities."}
