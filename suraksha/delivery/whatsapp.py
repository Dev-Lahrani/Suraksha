"""WhatsApp Cloud API (Meta) — text + voice-note delivery."""

from __future__ import annotations

import logging

import httpx

from suraksha.config import get_settings

logger = logging.getLogger(__name__)

GRAPH_VERSION = "v21.0"


def configured() -> bool:
    s = get_settings()
    return bool(s.whatsapp_token and s.whatsapp_phone_number_id)


async def send_text(to: str, body: str) -> bool:
    """Send a plain text message. Returns success."""
    return await _send_payload(
        to,
        {"type": "text", "text": {"preview_url": False, "body": body[:4096]}},
    )


async def send_voice_note(to: str, ogg_data: bytes) -> bool:
    """Upload audio and deliver it as a WhatsApp voice note (ogg/opus)."""
    if not configured():
        logger.info("WhatsApp not configured; skipping voice note (%d bytes)", len(ogg_data))
        return False
    s = get_settings()
    base = f"https://graph.facebook.com/{GRAPH_VERSION}/{s.whatsapp_phone_number_id}"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            up = await client.post(
                f"{base}/media",
                headers={"Authorization": f"Bearer {s.whatsapp_token}"},
                data={"messaging_product": "whatsapp", "type": "audio"},
                files={"file": ("advisory.ogg", ogg_data, "audio/ogg")},
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
    if not configured():
        logger.info("WhatsApp not configured; would send to %s: %s", to, payload.get("type"))
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


def extract_webhook_event(payload: dict) -> dict | None:
    """Parse a Cloud API webhook payload.

    Returns {from, text, timestamp} for text messages, {from, type: 'audio',
    timestamp} for voice notes, or None for anything else (status updates,
    media we can't interpret, etc.).
    """
    try:
        entries = payload.get("entry", [])
        for entry in entries:
            for change in entry.get("changes", []):
                value = change.get("value", {})
                messages = value.get("messages")
                if not messages:
                    continue
                msg = messages[0]
                if msg.get("type") == "text":
                    return {
                        "from": msg.get("from", ""),
                        "text": msg.get("text", {}).get("body", ""),
                        "timestamp": msg.get("timestamp", ""),
                    }
                if msg.get("type") == "audio":
                    # Indic ASR input is a stretch goal (decision.md D18); for
                    # now a voice note triggers the voice-advisory flow.
                    return {
                        "from": msg.get("from", ""),
                        "type": "audio",
                        "timestamp": msg.get("timestamp", ""),
                    }
    except (AttributeError, IndexError, KeyError, TypeError):
        return None
    return None
