"""Web Push (VAPID) delivery for browser subscribers — no phone number needed.

Generate keys once:  python -m suraksha vapid   (prints env lines)
Degrades gracefully: without keys or the pywebpush package nothing is sent.
"""

from __future__ import annotations

import asyncio
import json
import logging

from suraksha.config import get_settings

logger = logging.getLogger(__name__)


def configured() -> bool:
    s = get_settings()
    if not (s.vapid_private_key and s.vapid_public_key):
        return False
    try:
        import pywebpush  # noqa: F401
    except ImportError:
        return False
    return True


def _send_sync(sub, payload: str) -> str:
    from pywebpush import WebPushException, webpush

    s = get_settings()
    try:
        webpush(
            subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
            data=payload,
            vapid_private_key=s.vapid_private_key,
            vapid_claims={"sub": s.vapid_subject},
            ttl=6 * 3600,
        )
        return "ok"
    except WebPushException as exc:
        status = getattr(exc.response, "status_code", None)
        if status in (404, 410):
            return "gone"
        logger.error("web push failed (%s): %s", status, exc)
        return "error"
    except Exception as exc:  # noqa: BLE001
        logger.error("web push failed: %s", exc)
        return "error"


async def send(sub, title: str, body: str, district_id: str) -> str:
    """Returns 'ok', 'gone' (endpoint expired) or 'error'."""
    if not configured():
        return "error"
    payload = json.dumps({"title": title, "body": body, "district_id": district_id})
    return await asyncio.to_thread(_send_sync, sub, payload)


def generate_keys() -> tuple[str, str]:
    """(private_key_pem_b64url, public_key_b64url) usable as VAPID_* settings."""
    import base64

    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid

    v = Vapid()
    v.generate_keys()
    raw_priv = v.private_key.private_numbers().private_value.to_bytes(32, "big")
    pub = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()  # noqa: E731
    return b64(raw_priv), b64(pub)
