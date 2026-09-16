"""Proactive alerting: subscriber sweep that pushes alerts over WhatsApp.

The scheduler runs `sweep_subscribers()` once a day (and it can be triggered
manually via POST /api/alerts/sweep). Like every Suraksha delivery path it
degrades gracefully: no WhatsApp credentials → nothing is sent and nothing is
marked as alerted, and the whole sweep is idempotent thanks to the
(subscriber, day, reason) unique key on AlertLog.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy.orm import Session

from suraksha.core.anomaly import detect_anomalies
from suraksha.db import AlertLog, District, RiskScore, SessionLocal, Subscriber
from suraksha.delivery import whatsapp

logger = logging.getLogger(__name__)

# Look this many days ahead for a high-band forecast day (peaks matter more
# than the exact day it crosses the threshold).
RISK_LOOKAHEAD_DAYS = 2

# Don't re-alert the same reason (e.g. high flood risk) within this window —
# a multi-day hazard triggers one push, not one per day.
DEDUPE_DAYS = 3


def subscribe(session_id: str, district_id: str, language: str = "en") -> None:
    """Activate (or create) a subscriber for one district."""
    with SessionLocal() as db:  # type: Session
        s = db.get(Subscriber, session_id)
        if s is None:
            s = Subscriber(
                id=session_id,
                district_id=district_id,
                language=language,
                active=True,
                created_at=date.today().isoformat(),
            )
            db.add(s)
        else:
            s.district_id = district_id
            s.language = language
            s.active = True
        db.commit()


def unsubscribe(session_id: str) -> bool:
    """Deactivate a subscriber. Returns True if an active subscription existed."""
    with SessionLocal() as db:  # type: Session
        s = db.get(Subscriber, session_id)
        if s is None or not s.active:
            return False
        s.active = False
        db.commit()
        return True


async def sweep_subscribers() -> dict:
    """One pass over all active subscribers: push new alerts, log, dedupe."""
    with SessionLocal() as db:  # type: Session
        subs = db.query(Subscriber).filter(Subscriber.active.is_(True)).all()
        sub_ids = [s.id for s in subs]

    if not sub_ids:
        return {"subscribers": 0, "alerted": 0, "reasons": [], "skipped": 0}

    if not whatsapp.configured():
        logger.info("alert sweep skipped: WhatsApp not configured (%d subscribers)", len(sub_ids))
        return {"subscribers": len(sub_ids), "alerted": 0, "reasons": [], "skipped": len(sub_ids)}

    alerted = 0
    skipped = 0
    reasons_sent: list[str] = []
    for sid in sub_ids:
        try:
            sent = await _alert_one(sid)
        except Exception:  # noqa: BLE001 — one bad subscriber must not stop the sweep
            logger.exception("alert sweep failed for subscriber %s", sid)
            skipped += 1
            continue
        if sent:
            alerted += 1
            reasons_sent.extend(sent)
        else:
            skipped += 1

    logger.info("alert sweep done: %d alerted, %d skipped", alerted, skipped)
    return {
        "subscribers": len(sub_ids),
        "alerted": alerted,
        "reasons": reasons_sent,
        "skipped": skipped,
    }


async def _alert_one(subscriber_id: str) -> list[str]:
    """Build + send one subscriber's alert. Returns the reasons that were pushed."""
    with SessionLocal() as db:  # type: Session
        s = db.get(Subscriber, subscriber_id)
        if s is None or not s.active:
            return []
        lang = s.language or "en"
        d = db.get(District, s.district_id)
        if d is None:
            return []
        district = {
            "id": d.id,
            "name_en": d.name_en,
            "name_hi": d.name_hi,
            "name_mr": d.name_mr,
            "state": d.state,
        }

        hazards = _high_risk_hazards(db, s.district_id)
        anomalies = detect_anomalies(s.district_id, lookback_days=2)

        # Dedupe: exact (day, reason) rows already sent, plus any same-reason
        # alert in the last DEDUPE_DAYS so persistent hazards don't spam daily.
        recent_cutoff = date.today() - timedelta(days=DEDUPE_DAYS)
        alerts = db.query(AlertLog).filter(AlertLog.subscriber_id == subscriber_id).all()
        existing = {(a.day, a.reason) for a in alerts}
        recent_reasons = {a.reason for a in alerts if a.day and a.day >= recent_cutoff}
        fresh: list[tuple[date, str]] = []
        for h in hazards:
            reason = f"high_risk:{h['hazard']}"
            key = (h["_day"], reason)
            if key not in existing and reason not in recent_reasons:
                fresh.append(key)
        for e in anomalies:
            reason = f"anomaly:{e['kind']}"
            key = (date.fromisoformat(e["day"]), reason)
            if key not in existing and reason not in recent_reasons:
                fresh.append(key)

        if not fresh:
            return []

        from suraksha.agent.i18n import format_alert

        text = format_alert(district, hazards, anomalies, lang)
        ok = await whatsapp.send_text(subscriber_id, text)
        if not ok:
            logger.warning("alert send failed for %s; will retry next sweep", subscriber_id)
            return []

        today_iso = date.today().isoformat()
        now_iso = _utcnow_iso()
        for day, reason in fresh:
            db.add(
                AlertLog(
                    subscriber_id=subscriber_id,
                    district_id=s.district_id,
                    day=day,
                    reason=reason,
                    channel="whatsapp",
                    sent_at=now_iso,
                )
            )
        s.last_alerted_day = today_iso
        db.commit()
        return [f"{day.isoformat()}:{reason}" for day, reason in fresh]


def _high_risk_hazards(db: Session, district_id: str) -> list[dict]:
    """High-band risk rows in the lookahead window, formatted like advisory hazards."""
    from suraksha.agent.i18n import playbook_actions

    today = date.today()
    rows = (
        db.query(RiskScore)
        .filter(
            RiskScore.district_id == district_id,
            RiskScore.band == "high",
            RiskScore.day >= today,
            RiskScore.day <= today + timedelta(days=RISK_LOOKAHEAD_DAYS),
        )
        .order_by(RiskScore.day)
        .all()
    )
    out: list[dict] = []
    for r in rows:
        detail: dict = {}
        try:
            import json

            detail = json.loads(r.detail or "{}")
        except json.JSONDecodeError:
            pass
        out.append(
            {
                "hazard": r.hazard,
                "score": r.score or 0.0,
                "band": r.band or "high",
                "detail": detail,
                "actions": playbook_actions(r.hazard, "high", "en"),
                "_day": r.day,
            }
        )
    return out


def _utcnow_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
