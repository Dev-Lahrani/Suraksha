"""Advisor: composes grounded advisories; LLM phrases, never invents numbers."""

from __future__ import annotations

import logging

from suraksha.agent import llm
from suraksha.agent.i18n import detect_language
from suraksha.agent.tools import advisory_text, district_context
from suraksha.config import get_settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Suraksha, a climate early-warning assistant for Indian districts.

STRICT GROUNDING RULES:
1. Use ONLY the numbers in the provided context (risk scores, heat index, rainfall, AQI, anomalies). Never invent or round beyond what is given.
2. Write in the requested language ({lang}): simple, warm, no jargon. Short sentences.
3. Present the highest-risk hazard first. Always include the concrete safety actions given in the playbook.
4. End with one line: "Sources: Open-Meteo (ERA5 + forecast), NDMA guidelines."
5. Maximum 120 words. This will be sent on WhatsApp."""


async def compose_advisory(district_id: str, language: str | None = None) -> tuple[str, str, bool]:
    """Returns (text, language, llm_used). Falls back to templates when no LLM."""
    ctx = district_context(district_id)
    district = ctx.get("district")
    if not district:
        return "District not found. Try 'Pune' or 'Delhi'.", "en", False
    lang = language or "en"
    fallback_text, _ = advisory_text(district_id, lang)
    if not llm or not (
        get_settings().nugen_api_key or get_settings().openai_api_key
    ):
        return fallback_text, lang, False

    from suraksha.agent.tools import build_hazard_list

    hazards = build_hazard_list(ctx, lang)
    user_prompt = (
        f"District: {district['name_en']} ({district['state']}), population ~{district['population']:,}.\n"
        f"Language: {lang}\n"
        f"Data:\n{fallback_text}\n\n"
        "Rewrite this advisory warmly and clearly in the same language, keeping every number identical. "
        "Keep the emoji headers and the action lines (➜)."
    )
    reply = await llm.chat(
        [
            {"role": "system", "content": SYSTEM_PROMPT.format(lang=lang)},
            {"role": "user", "content": user_prompt},
        ]
    )
    if not reply:
        return fallback_text, lang, False
    return reply.strip(), lang, True


def digest_text(district_id: str, language: str = "en") -> str:
    """Short proactive bulletin for scheduled pushes (deterministic)."""
    text, _ = advisory_text(district_id, language)
    lines = text.splitlines()
    header = lines[0] if lines else ""
    top: list[str] = []
    for ln in lines[1:]:
        if ln.startswith(("🔥", "🌊", "😷")) and "Unknown" not in ln and "अज्ञात" not in ln:
            top.append(ln)
        if len(top) == 2:
            break
    actions: list[str] = [ln for ln in lines if ln.strip().startswith("➜")][:2]
    return "\n".join([header, *top, *actions, "📍 Sources: Open-Meteo, NDMA guidelines."])
