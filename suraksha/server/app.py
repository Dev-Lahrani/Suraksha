"""FastAPI application exposing the dashboard, chat, webhook and brief APIs."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy.orm import Session

from suraksha.agent import brain
from suraksha.agent.i18n import detect_language
from suraksha.agent.tools import advisory_text, district_context, find_district, forecast_text
from suraksha.config import get_settings
from suraksha.data.pipeline import run_pipeline
from suraksha.db import AirQuality, District, RiskScore, SessionLocal, Subscriber, get_db, init_db
from suraksha.ml.runner import ml_outlook, model_summary
from suraksha.delivery import voice, whatsapp
from suraksha.delivery.alerts import subscribe, sweep_subscribers, unsubscribe
from suraksha.delivery.pdf_brief import build_brief

logger = logging.getLogger(__name__)
WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@asynccontextmanager
async def lifespan(_: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    init_db()
    logger.info("Suraksha API ready")
    yield


app = FastAPI(title="Suraksha API", version="0.1.0", lifespan=lifespan)


# ----------------------------- Dashboard SPA -----------------------------

@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/app.js")
def app_js() -> FileResponse:
    return FileResponse(WEB_DIR / "app.js")


@app.get("/blocked.html")
def blocked_page() -> FileResponse:
    return FileResponse(WEB_DIR / "blocked.html")


# ----------------------------- Core API -----------------------------

@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "time": date.today().isoformat()}


@app.get("/api/districts")
def list_districts(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(District).order_by(District.state, District.name_en).all()
    return [
        {
            "id": d.id,
            "name_en": d.name_en,
            "name_hi": d.name_hi,
            "name_mr": d.name_mr,
            "state": d.state,
            "lat": d.lat,
            "lon": d.lon,
            "population": d.population,
        }
        for d in rows
    ]


@app.get("/api/risk-map")
def risk_map(day: str | None = None, db: Session = Depends(get_db)) -> list[dict]:
    """Latest risk per district per hazard (for the map; day = YYYY-MM-DD)."""
    q = db.query(RiskScore)
    if day:
        q = q.filter(RiskScore.day == date.fromisoformat(day))
    rows = q.all()
    latest: dict[str, dict] = {}
    for r in rows:
        cur = latest.setdefault(r.district_id, {})
        cur[r.hazard] = {"score": r.score, "band": r.band}
    districts = {d.id: d for d in db.query(District).all()}
    out = []
    for did, hazards in latest.items():
        d = districts.get(did)
        if not d:
            continue
        overall = max((h["score"] or 0) for h in hazards.values()) if hazards else 0
        out.append(
            {
                "id": did,
                "name_en": d.name_en,
                "name_hi": d.name_hi,
                "name_mr": d.name_mr,
                "state": d.state,
                "lat": d.lat,
                "lon": d.lon,
                "population": d.population,
                "hazards": hazards,
                "overall": round(overall, 1),
            }
        )
    return out


@app.get("/api/district/{district_id}")
def district_detail(district_id: str, lang: str = "en") -> dict:
    ctx = district_context(district_id)
    if not ctx:
        raise HTTPException(404, f"Unknown district {district_id}")
    advisory, _ = advisory_text(district_id, lang)
    return {**ctx, "advisory": advisory}


@app.get("/api/district/{district_id}/forecast")
def district_forecast(district_id: str) -> list[dict]:
    ctx = district_context(district_id)
    if not ctx:
        raise HTTPException(404, f"Unknown district {district_id}")
    return ctx.get("forecast", [])


@app.get("/api/district/{district_id}/air-quality")
def district_air(district_id: str, db: Session = Depends(get_db)) -> list[dict]:
    since = (date.today() - timedelta(days=2)).isoformat()
    rows = (
        db.query(AirQuality)
        .filter(AirQuality.district_id == district_id, AirQuality.hour >= since)
        .order_by(AirQuality.hour)
        .all()
    )
    return [{"hour": r.hour, "pm25": r.pm25, "pm10": r.pm10} for r in rows]


@app.get("/api/district/{district_id}/advisory")
def district_advisory(district_id: str, lang: str = "en") -> dict:
    text, language = advisory_text(district_id, lang)
    return {"text": text, "language": language}


@app.get("/api/district/{district_id}/forecast-text")
def district_forecast_text(district_id: str, lang: str = "en") -> dict:
    return {"text": forecast_text(district_id, lang)}


@app.get("/api/district/{district_id}/ml-outlook")
def district_ml_outlook(district_id: str) -> dict:
    """GBM outlook rows + validation metadata, or {} when no honest model exists.

    Per decision.md D12 the forecaster ships only when it beats the
    climatology baseline — an empty object here is a valid answer, not an error.
    """
    ctx = district_context(district_id)
    if not ctx:
        raise HTTPException(404, f"Unknown district {district_id}")
    rows = ml_outlook(district_id)
    return {
        "available": rows is not None,
        "rows": rows or [],
        "validation": model_summary(district_id),
    }


@app.get("/api/district/{district_id}/brief.pdf")
def district_brief(district_id: str) -> Response:
    try:
        pdf = build_brief(district_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return Response(pdf, media_type="application/pdf")


@app.post("/api/district/{district_id}/voice")
async def district_voice(district_id: str, lang: str = "hi") -> Response:
    text, language = advisory_text(district_id, lang)
    audio, is_tts = await voice.synthesize(text, language)
    return Response(
        audio,
        media_type="audio/ogg" if is_tts else "audio/wav",
        headers={"X-TTS-Engine": "edge-tts" if is_tts else "fallback"},
    )


@app.post("/api/chat")
async def chat(request: Request) -> dict:
    body = await request.json()
    session_id = str(body.get("session_id") or "web")[:128]
    message = str(body.get("message") or "")
    if not message.strip():
        raise HTTPException(400, "message required")
    reply = await brain.handle_message(session_id, message)
    return {"reply": reply}


@app.post("/api/ingest")
async def ingest(force: bool = False) -> dict:
    """Manual pipeline trigger (also run hourly by the scheduler)."""
    summary = await run_pipeline(force=force)
    return JSONResponse(summary)


# ----------------------------- Subscriptions & alerts -----------------------------

@app.post("/api/subscribers")
async def create_subscriber(request: Request) -> dict:
    """Register a subscriber (id + district). Used by the dashboard button too."""
    body = await request.json()
    sid = str(body.get("id") or "").strip()[:128]
    district_id = str(body.get("district_id") or "").strip()
    if not sid or not district_id:
        raise HTTPException(400, "id and district_id required")
    with SessionLocal() as db:
        if not db.get(District, district_id):
            raise HTTPException(400, f"Unknown district {district_id}")
    subscribe(sid, district_id, str(body.get("language") or "en"))
    return {"status": "subscribed", "id": sid, "district_id": district_id}


@app.get("/api/subscribers/{subscriber_id}")
def get_subscriber(subscriber_id: str, response: Response) -> dict:
    with SessionLocal() as db:
        s = db.get(Subscriber, subscriber_id)
        if not s:
            raise HTTPException(404, "Not subscribed")
        d = db.get(District, s.district_id)
        response.headers["X-Subscription-Active"] = "1" if s.active else "0"
        return {
            "id": s.id,
            "district_id": s.district_id,
            "district": d.name_en if d else None,
            "language": s.language,
            "active": s.active,
            "last_alerted_day": s.last_alerted_day,
        }


@app.delete("/api/subscribers/{subscriber_id}")
def delete_subscriber(subscriber_id: str) -> dict:
    if not unsubscribe(subscriber_id):
        raise HTTPException(404, "Not subscribed")
    return {"status": "unsubscribed"}


@app.delete("/api/subscribers/{subscriber_id}/hard")
def delete_subscriber_hard(subscriber_id: str) -> dict:
    """Remove the subscription row entirely (GDPR-style delete)."""
    with SessionLocal() as db:
        s = db.get(Subscriber, subscriber_id)
        if not s:
            raise HTTPException(404, "Not subscribed")
        db.delete(s)
        db.commit()
    return {"status": "deleted"}


@app.post("/api/alerts/sweep")
async def alerts_sweep() -> dict:
    """Run the proactive-alert sweep now (normally a daily scheduler job)."""
    return JSONResponse(await sweep_subscribers())


# ----------------------------- WhatsApp webhook -----------------------------

@app.get("/webhook/whatsapp")
def whatsapp_verify(mode: str = Query(""), token: str = Query(""), challenge: str = Query("")):
    s = get_settings()
    if mode == "subscribe" and token == s.whatsapp_verify_token:
        return Response(challenge)
    raise HTTPException(403, "verification failed")


@app.post("/webhook/whatsapp")
async def whatsapp_incoming(request: Request) -> dict:
    payload = await request.json()
    logger.info("WhatsApp webhook received")
    event = whatsapp.extract_webhook_event(payload)
    if not event:
        return {"status": "ignored"}
    if event.get("type") == "audio":
        # Voice note from the user → reply with the voice advisory flow.
        reply = await brain.handle_message(event["from"], "voice")
    else:
        reply = await brain.handle_message(event["from"], event["text"])
    ok = await whatsapp.send_text(event["from"], reply)
    return {"status": "ok" if ok else "send-failed"}


# ----------------------------- convenience -----------------------------

@app.get("/api/resolve")
def resolve(name: str, db: Session = Depends(get_db)) -> dict:
    d = find_district(name, db)
    if not d:
        raise HTTPException(404, f"No district matches '{name}'")
    return {"id": d.id, "name_en": d.name_en, "state": d.state}
