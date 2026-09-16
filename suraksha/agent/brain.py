"""Chat brain for WhatsApp and web chat: intent → tools → grounded LLM answer."""

from __future__ import annotations

import logging
import re
from datetime import date

from suraksha.agent import llm
from suraksha.agent.i18n import (
    detect_language,
    format_advisory,
    format_forecast,
    ask_which_district,
    stopped_text,
    subscribed_text,
    voice_sent_text,
)
from suraksha.agent.tools import advisory_text, district_context, find_district
from suraksha.config import get_settings
from suraksha.db import ChatSession, District, SessionLocal
from suraksha.delivery.alerts import subscribe, unsubscribe

logger = logging.getLogger(__name__)

INTENTS = ("advisory", "forecast", "anomaly")

_SYSTEM = """You are Suraksha, a friendly climate early-warning assistant on WhatsApp for India.
Rules:
1. Ground every number in the CONTEXT provided. Never invent numbers.
2. Reply in the user's language (en/hi/mr). Keep it under 120 words, WhatsApp style.
3. If the user's district is unclear, ask which district they mean.
4. Include relevant safety actions when risk is moderate or high."""

_DISTRICT_HINT = re.compile(
    r"(?:in|for|of|at|me|में|मध्ये|के लिए|साठी)\s+([A-Za-z\u0900-\u097F][A-Za-z\u0900-\u097F\s\-]{1,40})"
)

# Subscription commands are short, explicit messages — anything longer than a
# phrase is a normal question even if it happens to contain the word "stop".
# Note: \b word boundaries are unreliable around Devanagari matras (combining
# marks are not \w), so Indic patterns match as plain substrings and "stop" is
# checked before "subscribe" ("unsubscribe" must win over its own substring).
_STOP_RE = re.compile(r"\b(stop|unsubscribe)\b|रद्द कर|बंद कर|सदस्यता रद्द", re.IGNORECASE)
_SUBSCRIBE_RE = re.compile(r"subscribe|सदस्यता", re.IGNORECASE)


def _get_session(session_id: str) -> ChatSession:
    with SessionLocal() as db:
        s = db.get(ChatSession, session_id)
        if s is None:
            s = ChatSession(id=session_id, language="en", created_at=date.today().isoformat())
            db.add(s)
            db.commit()
        return s


def _set_session(session_id: str, language: str | None = None, district_id: str | None = None) -> None:
    with SessionLocal() as db:
        s = db.get(ChatSession, session_id)
        if s is None:
            s = ChatSession(id=session_id, created_at=date.today().isoformat())
            db.add(s)
        if language:
            s.language = language
        if district_id:
            s.district_id = district_id
        db.commit()


async def handle_message(session_id: str, text: str) -> str:
    """Main entry point used by both the WhatsApp webhook and the web chat API."""
    text = (text or "").strip()
    lang = detect_language(text)
    _set_session(session_id, language=lang)

    # Subscription commands take priority over advisory flows.
    sub_cmd = _subscription_command(text)
    if sub_cmd == "stop":
        unsubscribe(session_id)
        return stopped_text(lang)
    if sub_cmd == "subscribe":
        return _handle_subscribe(session_id, text, lang)

    # "VOICE <district>" (or a remembered district) → send the advisory as a
    # WhatsApp voice note for low-literacy users (headline feature #3).
    voice_req, voice_text = _voice_command(text)
    if voice_req:
        return await _handle_voice_request(session_id, voice_text, lang)

    district = _resolve_district(text)
    if district is None:
        sess = _get_session(session_id)
        if sess.district_id:
            district_id = sess.district_id
            district = None
        else:
            return ask_which_district(lang)
    else:
        district_id = district.id

    _set_session(session_id, district_id=district_id)
    intent = _detect_intent(text)
    ctx = district_context(district_id)

    if not ctx:
        return "Sorry, I couldn't load that district's data. Please try another name."

    # Deterministic paths first — they always work, LLM only improves phrasing.
    if intent == "forecast":
        return format_forecast(ctx["district"], ctx.get("forecast", []), lang)
    if intent == "advisory":
        base_text, _ = advisory_text(district_id, lang)
        if not _llm_configured():
            return base_text
        return await _llm_ground(ctx, base_text, lang)
    if intent == "anomaly":
        from suraksha.agent.tools import anomaly_text

        reply = anomaly_text(district_id, lang)
        if _llm_configured():
            reply = await _llm_ground(ctx, reply, lang)
        return reply

    # General chit-chat / unclear intent: grounded LLM answer or help text.
    base_text, _ = advisory_text(district_id, lang)
    if _llm_configured():
        return await _llm_ground(ctx, base_text, lang)
    return base_text


_VOICE_RE = re.compile(r"^\s*(voice|audio|ऑडियो|व्हॉइस|आवाज़)\b(.*)$", re.IGNORECASE | re.DOTALL)


def _voice_command(text: str) -> tuple[bool, str]:
    """Detect a voice-note request; return (is_voice_request, remainder_text)."""
    m = _VOICE_RE.match(text or "")
    if not m:
        return False, ""
    return True, m.group(2).strip()


async def _handle_voice_request(session_id: str, text: str, lang: str) -> str:
    """Compose the advisory, synthesize audio, push it as a WhatsApp voice note."""
    from suraksha.delivery import voice, whatsapp

    district = _resolve_district(text)
    if district is None:
        sess = _get_session(session_id)
        if sess.district_id:
            with SessionLocal() as db:
                district = db.get(District, sess.district_id)
        if district is None:
            return ask_which_district(lang)
    _set_session(session_id, district_id=district.id)
    base_text, audio_lang = advisory_text(district.id, lang)
    audio, is_tts = await voice.synthesize(base_text, audio_lang)
    if is_tts and whatsapp.configured():
        ok = await whatsapp.send_voice_note(session_id, audio)
        if ok:
            return voice_sent_text(audio_lang)
    # Any fallback path: return the text with an explicit note about the audio.
    return base_text + "\n\n" + voice_sent_text(audio_lang)


def _handle_subscribe(session_id: str, text: str, lang: str) -> str:
    """SUBSCRIBE <district> (or bare SUBSCRIBE using the remembered district)."""
    district = _resolve_district(text)
    if district is None:
        sess = _get_session(session_id)
        if sess.district_id:
            with SessionLocal() as db:
                district = db.get(District, sess.district_id)
        if district is None:
            return ask_which_district(lang)
    subscribe(session_id, district.id, lang)
    name = {"en": district.name_en, "hi": district.name_hi, "mr": district.name_mr}.get(lang) or district.name_en
    return subscribed_text(name, lang)


def _subscription_command(text: str) -> str | None:
    """Classify a message as a subscription command, or None."""
    t = (text or "").strip()
    if _STOP_RE.search(t):
        return "stop"
    if _SUBSCRIBE_RE.search(t):
        return "subscribe"
    return None


def _resolve_district(text: str):
    """Try explicit match, then 'in <district>' hint regex, then session memory."""
    with SessionLocal() as db:
        d = find_district(text, db)
    if d:
        return d
    m = _DISTRICT_HINT.search(text)
    if m:
        candidate = m.group(1).strip()
        with SessionLocal() as db:
            d = find_district(candidate, db)
        if d:
            return d
    return None


def _detect_intent(text: str) -> str:
    t = text.lower()
    if any(w in t for w in ("forecast", "मौसम", "हवामान", "अंदाज", "अनुमान", "अगले", "पुढील")):
        return "forecast"
    if any(w in t for w in ("anomal", "unusual", "सामान्य से", "विसंगत", "असामान्य")):
        return "anomaly"
    return "advisory"


def _llm_configured() -> bool:
    s = get_settings()
    return bool(s.nugen_api_key or s.openai_api_key)


async def _llm_ground(ctx: dict, base_text: str, lang: str) -> str:
    district = ctx["district"]
    prompt = (
        f"User's district: {district['name_en']} ({district['state']}).\n"
        f"Language: {lang}\nCONTEXT (use only these numbers):\n{base_text}\n\n"
        "Answer the user naturally in the same language using only this context. "
        "Keep action lines (➜) and the sources line."
    )
    reply = await llm.chat(
        [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": prompt},
        ]
    )
    return reply.strip() if reply else base_text
