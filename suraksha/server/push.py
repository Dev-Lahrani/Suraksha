"""Browser Web Push subscription API (public; rate limited, validated)."""

import hashlib
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from suraksha.agent.i18n import LANGUAGES
from suraksha.core.clock import india_today
from suraksha.delivery.alerts import normalize_prefs
from suraksha.db import District, PushSubscription, get_db
from suraksha.delivery import webpush
from suraksha.config import get_settings
from suraksha.server.ratelimit import rate_limited

router = APIRouter(prefix="/api/push")


class Keys(BaseModel):
    p256dh: str = Field(min_length=10, max_length=200)
    auth: str = Field(min_length=10, max_length=100)


class PushIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    endpoint: str = Field(max_length=1024)
    keys: Keys
    district_id: str = Field(min_length=1, max_length=64)
    language: str = "en"
    hazards: list[str] | None = Field(default=None, max_length=3)
    min_score: float | None = None


class PushOut(BaseModel):
    endpoint: str = Field(max_length=1024)


def _sub_id(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode()).hexdigest()[:32]


def _check_endpoint(endpoint: str) -> None:
    # Push services are always https; this also blocks SSRF to internal hosts
    # (the server POSTs to this URL when delivering).
    parsed = urlparse(endpoint)
    host = parsed.hostname or ""
    if parsed.scheme != "https" or "." not in host or host.replace(".", "").isdigit() or host == "localhost":
        raise HTTPException(422, "Invalid push endpoint")


@router.get("/key")
def public_key() -> dict:
    # 200 even when disabled so browsers do not log a failed request.
    if not webpush.configured():
        return {"enabled": False, "public_key": None}
    return {"enabled": True, "public_key": get_settings().vapid_public_key}


@router.post("/subscribe", dependencies=[Depends(rate_limited("push"))])
def subscribe(body: PushIn, db: Session = Depends(get_db)) -> dict:
    if not webpush.configured():
        raise HTTPException(503, "Web Push is not configured")
    _check_endpoint(body.endpoint)
    if body.language not in LANGUAGES:
        raise HTTPException(422, "Unsupported language")
    if db.get(District, body.district_id) is None:
        raise HTTPException(404, f"Unknown district {body.district_id}")
    try:
        csv, min_score = normalize_prefs(body.hazards, body.min_score)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    sid = _sub_id(body.endpoint)
    sub = db.get(PushSubscription, sid) or PushSubscription(id=sid, created_at=india_today().isoformat())
    sub.endpoint, sub.p256dh, sub.auth = body.endpoint, body.keys.p256dh, body.keys.auth
    sub.district_id, sub.language = body.district_id, body.language
    if csv is not None:
        sub.hazards = csv
    if min_score is not None:
        sub.min_score = min_score
    db.add(sub)
    db.commit()
    return {"status": "subscribed", "district_id": body.district_id,
            "hazards": sub.hazards or "heat,flood,air", "min_score": sub.min_score or 60.0}


@router.post("/unsubscribe", dependencies=[Depends(rate_limited("push"))])
def unsubscribe(body: PushOut, db: Session = Depends(get_db)) -> dict:
    sub = db.get(PushSubscription, _sub_id(body.endpoint))
    if sub is None:
        raise HTTPException(404, "Not subscribed")
    db.delete(sub)
    db.commit()
    return {"status": "unsubscribed"}
