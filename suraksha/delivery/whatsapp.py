"""WhatsApp Cloud API (Meta) — text + voice-note delivery."""

from __future__ import annotations

import logging
import re

import httpx

from suraksha.config import get_settings

logger = logging.getLogger(__name__)

GRAPH_VERSION = "v21.0"


_PHONE_RE = re.compile(r"^\d{8,15}$")


def is_whatsapp_id(session_id: str) -> bool:
    """Only bare international phone numbers (as sent by Meta) are deliverable.

    Web chat IDs are prefixed ("web:") so a browser client can never target a
    phone number.
    """
    return bool(_PHONE_RE.fullmatch(session_id or ""))


def configured() -> bool:
    s = get_settings()
    return bool(s.whatsapp_token and s.whatsapp_phone_number_id)


async def send_text(to: str, body: str) -> bool:
    """Send a plain text message. Returns success."""
    return await _send_payload(
        to,
        {"type": "text", "text": {"preview_url": False, "body": body[:4096]}},
    )


async def send_template(to: str, name: str, language: str, params: list[str]) -> bool:
    """Send an approved template (needed outside the 24h customer-service window)."""
    # Template variables may not contain newlines/tabs or 4+ consecutive spaces.
    clean = [re.sub(r"\s+", " ", p).strip()[:1024] for p in params]
    return await _send_payload(
        to,
        {
            "type": "template",
            "template": {
                "name": name,
                "language": {"code": language},
                "components": [
                    {"type": "body", "parameters": [{"type": "text", "text": p} for p in clean]}
                ],
            },
        },
    )


async def send_voice_note(to: str, ogg_data: bytes) -> bool:
    """Upload edge-tts MP3 as a WhatsApp audio message (not OGG/Opus)."""
    if not configured() or not is_whatsapp_id(to):
        logger.info("WhatsApp not configured or non-phone recipient; skipping voice note (%d bytes)", len(ogg_data))
        return False
    s = get_settings()
    base = f"https://graph.facebook.com/{GRAPH_VERSION}/{s.whatsapp_phone_number_id}"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            up = await client.post(
                f"{base}/media",
                headers={"Authorization": f"Bearer {s.whatsapp_token}"},
                data={"messaging_product": "whatsapp", "type": "audio"},
                files={"file": ("advisory.mp3", ogg_data, "audio/mpeg")},
            )
            up.raise_for_status()
            media_id = up.json().get("id")
            if not media_id:
                logger.error("WhatsApp media upload returned no id: %s", up.text)
                return False
            return await _send_payload(
                to, {"type": "audio", "audio": {"id": media_id}}
            )
    except Exception as exc:  # noqa: BLE001
        logger.error("WhatsApp voice-note send failed: %s", exc)
        return False


async def _send_payload(to: str, payload: dict) -> bool:
    if not configured() or not is_whatsapp_id(to):
        logger.info("WhatsApp not configured or non-phone recipient; not sending %s", payload.get("type"))
        return False
    s = get_settings()
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{s.whatsapp_phone_number_id}/messages"
    body = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to, **payload}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {s.whatsapp_token}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            if resp.status_code >= 400:
                logger.error("WhatsApp send error %s: %s", resp.status_code, resp.text)
                return False
            return True
    except Exception as exc:  # noqa: BLE001
        logger.error("WhatsApp send failed: %s", exc)
        return False


def extract_webhook_events(payload: dict) -> list[dict]:
    """Every text/audio message in a Cloud API payload (Meta batches them)."""
    events: list[dict] = []
    try:
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                for msg in change.get("value", {}).get("messages") or []:
                    base = {"from": msg.get("from", ""), "timestamp": msg.get("timestamp", "")}
                    if msg.get("id"):
                        base["id"] = msg["id"]
                    if msg.get("type") == "text":
                        events.append({**base, "text": msg.get("text", {}).get("body", "")})
                    elif msg.get("type") == "audio":
                        # Indic ASR input is a stretch goal (decision.md D18); for
                        # now a voice note triggers the voice-advisory flow.
                        events.append({**base, "type": "audio"})
    except (AttributeError, KeyError, TypeError):
        return events
    return events


def extract_webhook_event(payload: dict) -> dict | None:
    """First message of a payload (kept for callers that handle one event)."""
    events = extract_webhook_events(payload)
    return events[0] if events else None
