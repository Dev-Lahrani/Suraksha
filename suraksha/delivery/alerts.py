"""Proactive alerting: subscriber sweep that pushes alerts over WhatsApp.

The scheduler runs `sweep_subscribers()` once a day (and it can be triggered
manually via POST /api/alerts/sweep). Like every Suraksha delivery path it
degrades gracefully: no WhatsApp credentials → nothing is sent and nothing is
marked as alerted, and the whole sweep is idempotent thanks to the
(subscriber, day, reason) unique key on AlertLog.
"""

from __future__ import annotations

from suraksha.core.clock import india_today

import logging
from datetime import date, timedelta

from sqlalchemy.orm import Session

from suraksha.core.anomaly import detect_anomalies
from suraksha.db import AlertLog, District, PushSubscription, RiskScore, SessionLocal, Subscriber
from suraksha.delivery import whatsapp

logger = logging.getLogger(__name__)

# Look this many days ahead for a high-band forecast day (peaks matter more
# than the exact day it crosses the threshold).
RISK_LOOKAHEAD_DAYS = 2

# Don't re-alert the same reason (e.g. high flood risk) within this window —
# a multi-day hazard triggers one push, not one per day.
DEDUPE_DAYS = 3


HAZARD_IDS = ("heat", "flood", "air")
DEFAULT_MIN_SCORE = 60.0  # the "high" band


def normalize_prefs(hazards, min_score) -> tuple[str | None, float | None]:
    """Validate alert preferences; ValueError on bad input. None means 'unchanged'."""
    csv = None
    if hazards is not None:
        chosen = [str(h).strip().lower() for h in hazards]
        if not chosen or any(h not in HAZARD_IDS for h in chosen):
            raise ValueError("hazards must be a non-empty subset of heat, flood, air")
        csv = ",".join(h for h in HAZARD_IDS if h in chosen)
    if min_score is not None:
        min_score = float(min_score)
        if not 25 <= min_score <= 100:
            raise ValueError("min_score must be between 25 (moderate) and 100")
    return csv, min_score


def _pref_hazards(csv: str | None) -> set[str]:
    return {h for h in (csv or "").split(",") if h in HAZARD_IDS} or set(HAZARD_IDS)


def subscribe(session_id: str, district_id: str, language: str = "en",
              hazards=None, min_score=None) -> None:
    """Activate (or create) a subscriber for one district.

    Alert preferences are only changed when given, so re-subscribing keeps them.
    """
    csv, min_score = normalize_prefs(hazards, min_score)
    with SessionLocal() as db:  # type: Session
        s = db.get(Subscriber, session_id)
        if s is None:
            s = Subscriber(
                id=session_id,
                district_id=district_id,
                language=language,
                active=True,
                created_at=india_today().isoformat(),
            )
            db.add(s)
        else:
            s.district_id = district_id
            s.language = language
            s.active = True
        if csv is not None:
            s.hazards = csv
        if min_score is not None:
            s.min_score = min_score
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


async def _deliver(subscriber_id: str, text: str) -> bool:
    """Template message when configured (works outside the 24h window), else text."""
    from suraksha.config import get_settings

    s = get_settings()
    if s.whatsapp_alert_template:
        return await whatsapp.send_template(
            subscriber_id, s.whatsapp_alert_template, s.whatsapp_alert_template_lang, [text])
    return await whatsapp.send_text(subscriber_id, text)


async def sweep_subscribers(dry_run: bool = False) -> dict:
    """One pass over all active subscribers: push new alerts, log, dedupe.

    dry_run previews who would be alerted and why, without sending or logging.
    """
    with SessionLocal() as db:  # type: Session
        subs = db.query(Subscriber).filter(Subscriber.active.is_(True)).all()
        all_ids = [s.id for s in subs]
        sub_ids = [i for i in all_ids if whatsapp.is_whatsapp_id(i)]
        undeliverable = len(all_ids) - len(sub_ids)

    push = await sweep_push(dry_run)
    if not sub_ids:
        return {**push, "subscribers": 0, "alerted": 0, "reasons": [], "skipped": 0, "undeliverable": undeliverable}

    if not whatsapp.configured() and not dry_run:
        logger.info("alert sweep skipped: WhatsApp not configured (%d subscribers)", len(sub_ids))
        return {**push, "subscribers": len(sub_ids), "alerted": 0, "reasons": [], "skipped": len(sub_ids), "undeliverable": undeliverable}

    alerted = 0
    skipped = 0
    reasons_sent: list[str] = []
    for sid in sub_ids:
        try:
            sent = await _alert_one(sid, dry_run)
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
        **push,
        "subscribers": len(sub_ids),
        "alerted": alerted,
        "reasons": reasons_sent,
        "skipped": skipped,
        "undeliverable": undeliverable,
        "dry_run": dry_run,
    }


def _prepare(db: Session, key: str, district_id: str, lang: str,
             hazard_csv: str | None = None, min_score: float | None = None):
    """Hazards/anomalies for one recipient, minus what was already sent (dedupe).

    Returns (district dict, hazards, anomalies, fresh [(day, reason)], text) or None.
    """
    d = db.get(District, district_id)
    if d is None:
        return None
    district = {"id": d.id, "state": d.state,
                **{f"name_{c}": getattr(d, f"name_{c}") for c in ("en", "hi", "mr", "ta", "te", "kn", "bn")}}
    hazards = _high_risk_hazards(db, district_id, lang, _pref_hazards(hazard_csv),
                                 min_score if min_score is not None else DEFAULT_MIN_SCORE)
    anomalies = detect_anomalies(district_id, lookback_days=2)

    # Dedupe: exact (day, reason) rows already sent, plus any same-reason
    # alert in the last DEDUPE_DAYS so persistent hazards don't spam daily.
    recent_cutoff = india_today() - timedelta(days=DEDUPE_DAYS)
    alerts = db.query(AlertLog).filter(AlertLog.subscriber_id == key).all()
    existing = {(a.day, a.reason) for a in alerts}
    recent_reasons = {a.reason for a in alerts if a.day and a.day >= recent_cutoff}
    fresh: list[tuple[date, str]] = []
    for h in hazards:
        reason = f"high_risk:{h['hazard']}"
        k = (h["_day"], reason)
        if k not in existing and reason not in recent_reasons:
            fresh.append(k)
    for e in anomalies:
        reason = f"anomaly:{e['kind']}"
        k = (date.fromisoformat(e["day"]), reason)
        if k not in existing and reason not in recent_reasons:
            fresh.append(k)
    fresh = list(dict.fromkeys(fresh))
    if not fresh:
        return None
    from suraksha.agent.i18n import format_alert

    return district, hazards, anomalies, fresh, format_alert(district, hazards, anomalies, lang)


async def _send_logged(db: Session, key: str, district_id: str, channel: str, fresh, send) -> bool:
    """Record first, send second: a crash after a successful send can never
    re-alert; a failed send removes the rows so the next sweep retries."""
    now_iso = _utcnow_iso()
    logs = [AlertLog(subscriber_id=key, district_id=district_id, day=day, reason=reason,
                     channel=channel, sent_at=now_iso) for day, reason in fresh]
    db.add_all(logs)
    db.commit()
    if await send():
        return True
    for log in logs:
        db.delete(log)
    db.commit()
    return False


async def _alert_one(subscriber_id: str, dry_run: bool = False) -> list[str]:
    """Build + send one subscriber's alert. Returns the reasons that were pushed."""
    with SessionLocal() as db:  # type: Session
        s = db.get(Subscriber, subscriber_id)
        if s is None or not s.active:
            return []
        prepared = _prepare(db, subscriber_id, s.district_id, s.language or "en", s.hazards, s.min_score)
        if prepared is None:
            return []
        _, _, _, fresh, text = prepared
        reasons = [f"{day.isoformat()}:{reason}" for day, reason in fresh]
        if dry_run:
            return reasons
        if not await _send_logged(db, subscriber_id, s.district_id, "whatsapp", fresh,
                                  lambda: _deliver(subscriber_id, text)):
            logger.error("alert send FAILED for %s (district %s); will retry next sweep",
                         subscriber_id, s.district_id)
            return []
        s.last_alerted_day = india_today().isoformat()
        db.commit()
        return reasons


async def sweep_push(dry_run: bool = False) -> dict:
    """Web Push counterpart of the WhatsApp sweep (no phone number needed)."""
    from suraksha.delivery import webpush

    with SessionLocal() as db:
        ids = [r.id for r in db.query(PushSubscription.id)]
    if not ids:
        return {"push_subscribers": 0, "push_alerted": 0}
    if not webpush.configured() and not dry_run:
        return {"push_subscribers": len(ids), "push_alerted": 0, "push_skipped": "not configured"}
    alerted = 0
    for pid in ids:
        try:
            with SessionLocal() as db:
                sub = db.get(PushSubscription, pid)
                if sub is None:
                    continue
                prepared = _prepare(db, "push:" + pid, sub.district_id, sub.language or "en", sub.hazards, sub.min_score)
                if prepared is None:
                    continue
                district, hazards, _, fresh, text = prepared
                if dry_run:
                    alerted += 1
                    continue
                title = f"Suraksha: {district['name_en']}"
                result: dict = {}

                async def send():
                    result["r"] = await webpush.send(sub, title, text[:400], district["id"])
                    return result["r"] == "ok"

                if await _send_logged(db, "push:" + pid, sub.district_id, "push", fresh, send):
                    alerted += 1
                elif result.get("r") == "gone":  # browser unsubscribed: stop trying
                    db.delete(sub)
                    db.commit()
        except Exception:  # noqa: BLE001
            logger.exception("push alert failed for %s", pid)
    return {"push_subscribers": len(ids), "push_alerted": alerted}


def _high_risk_hazards(db: Session, district_id: str, language: str = "en",
                       hazards: set[str] | None = None, min_score: float = DEFAULT_MIN_SCORE) -> list[dict]:
    """Rows at/above the subscriber threshold in the lookahead window, formatted like advisory hazards."""
    from suraksha.agent.i18n import playbook_actions

    today = india_today()
    rows = (
        db.query(RiskScore)
        .filter(
            RiskScore.district_id == district_id,
            RiskScore.score >= min_score,
            RiskScore.hazard.in_(sorted(hazards or HAZARD_IDS)),
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
        detail["peak_day"] = r.day.isoformat()
        out.append(
            {
                "hazard": r.hazard,
                "score": r.score or 0.0,
                "band": r.band or "high",
                "detail": detail,
                "actions": playbook_actions(r.hazard, r.band or "high", language),
                "_day": r.day,
            }
        )
    return out


def _utcnow_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
