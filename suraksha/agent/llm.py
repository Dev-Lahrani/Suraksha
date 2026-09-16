"""LLM provider: Nugen-first (sponsor), OpenAI-compatible fallback, offline fallback.

The agent is *tool-grounded*: models and risk engines produce the numbers, and
the LLM only phrases them. If no API key is configured, we degrade gracefully
to the deterministic templates — the product never breaks.
"""

from __future__ import annotations

import json
import logging

import httpx

from suraksha.config import get_settings

logger = logging.getLogger(__name__)


async def chat(messages: list[dict], json_mode: bool = False) -> str:
    """Route to the configured provider; returns assistant text (never raises)."""
    s = get_settings()
    if s.nugen_api_key:
        try:
            return await _chat_openai_compatible(
                base_url=s.nugen_base_url,
                api_key=s.nugen_api_key,
                model=s.nugen_model,
                messages=messages,
                json_mode=json_mode,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Nugen call failed, trying fallback: %s", exc)
    if s.openai_api_key:
        try:
            return await _chat_openai_compatible(
                base_url=s.openai_base_url,
                api_key=s.openai_api_key,
                model="gpt-4o-mini",
                messages=messages,
                json_mode=json_mode,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("OpenAI fallback failed: %s", exc)
    return ""


async def _chat_openai_compatible(
    base_url: str, api_key: str, model: str, messages: list[dict], json_mode: bool
) -> str:
    payload: dict = {"model": model, "messages": messages, "temperature": 0.3, "max_tokens": 600}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


def parse_json_reply(text: str) -> dict | None:
    """Best-effort JSON extraction from an LLM reply."""
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
