"""i18n: playbooks, language detection and multilingual text formatting."""

from __future__ import annotations

import json
import re
from pathlib import Path

RESOURCES = Path(__file__).resolve().parents[2] / "resources"
_PLAYBOOKS = json.loads((RESOURCES / "playbooks.json").read_text(encoding="utf-8"))

LANGUAGES = ("en", "hi", "mr")

LABELS: dict[str, dict[str, str]] = {
    "en": {"heat": "Heat", "flood": "Flood", "air": "Air quality", "low": "Low", "moderate": "Moderate", "high": "High", "unknown": "Unknown"},
    "hi": {"heat": "गर्मी", "flood": "बाढ़", "air": "वायु गुणवत्ता", "low": "कम", "moderate": "मध्यम", "high": "उच्च", "unknown": "अज्ञात"},
    "mr": {"heat": "उष्मा", "flood": "पूर", "air": "हवेची गुणवत्ता", "low": "कमी", "moderate": "मध्यम", "high": "उच्च", "unknown": "अज्ञात"},
}

HAZARD_EMOJI = {"heat": "🔥", "flood": "🌊", "air": "😷"}

_INTRO: dict[str, str] = {
    "en": "🛡️ Suraksha advisory for {district} ({state})",
    "hi": "🛡️ सुरक्षा सलाह — {district} ({state})",
    "mr": "🛡️ सुरक्षा सलाह — {district} ({state})",
}

_ASK_DISTRICT: dict[str, str] = {
    "en": "Which district do you want the advisory for? e.g. 'Pune', 'Delhi', 'Wayanad'.",
    "hi": "किस ज़िले की सलाह चाहिए? जैसे 'पुणे', 'दिल्ली', 'वायनाड'।",
    "mr": "कोणत्या जिल्ह्याची सलाह हवी? उदा. 'पुणे', 'दिल्ली', 'वायनाड'.",
}

_FORECAST_HEADER: dict[str, str] = {
    "en": "🗓️ {district} — next {n} days:",
    "hi": "🗓️ {district} — अगले {n} दिन:",
    "mr": "🗓️ {district} — पुढील {n} दिवस:",
}

_NO_FORECAST: dict[str, str] = {
    "en": "No forecast data yet. The pipeline ingests Open-Meteo every hour — try again soon.",
    "hi": "अनुमान डेटा अभी उपलब्ध नहीं है। पाइपलाइन हर घंटे डेटा लाती है — थोड़ी देर बाद कोशिश करें।",
    "mr": "अंदाज डेटा अजून उपलब्ध नाही. पाइपलाइन दर तासाला डेटा आणते — थोड्या वेळाने प्रयत्न करा.",
}

_SUBSCRIBED: dict[str, str] = {
    "en": "✅ Subscribed! You will get a Suraksha alert for {district} when risk turns high or something unusual happens.\nSend 'STOP' anytime to unsubscribe.",
    "hi": "✅ सदस्यता ली गई! जब {district} में खतरा अधिक होगा या कुछ असामान्य होगा, तो आपको सुरक्षा अलर्ट मिलेगा।\nसदस्यता रद्द करने के लिए कभी भी 'STOP' भेजें।",
    "mr": "✅ सदस्यता घेतली! {district} मध्ये धोका जास्त असेल का सामान्य नसलेले काही घडले तर तुम्हाला सुरक्षा अलर्ट मिळेल.\nसदस्यता रद्द करण्यासाठी कधीही 'STOP' पाठवा.",
}

_STOPPED: dict[str, str] = {
    "en": "✅ Unsubscribed. You will not receive any more Suraksha alerts.\nSend 'SUBSCRIBE <district>' anytime to rejoin.",
    "hi": "✅ सदस्यता रद्द कर दी गई। अब आपको कोई सुरक्षा अलर्ट नहीं मिलेगा।\nदोबारा जुड़ने के लिए कभी भी 'SUBSCRIBE <ज़िला>' भेजें।",
    "mr": "✅ सदस्यता रद्द केली. आता तुम्हाला सुरक्षा अलर्ट मिळणार नाही.\nपुन्हा सामील होण्यासाठी कधीही 'SUBSCRIBE <जिल्हा>' पाठवा.",
}

_VOICE_SENT: dict[str, str] = {
    "en": "🎧 Advisory sent as a voice note.",
    "hi": "🎧 सलाह वॉयस नोट के रूप में भेज दी गई है।",
    "mr": "🎧 सलाह व्हॉइस नोट म्हणून पाठवली आहे.",
}

_ALERT_HEADER: dict[str, str] = {
    "en": "🚨 Suraksha alert — {district} ({state})",
    "hi": "🚨 सुरक्षा अलर्ट — {district} ({state})",
    "mr": "🚨 सुरक्षा अलर्ट — {district} ({state})",
}

_SOURCES_LINE = "📍 Sources: Open-Meteo (ERA5 + forecast), US-EPA AQI bands; actions: NDMA guidelines."


def subscribed_text(district_name: str, language: str = "en") -> str:
    lang = language if language in LANGUAGES else "en"
    return _SUBSCRIBED[lang].format(district=district_name)


def stopped_text(language: str = "en") -> str:
    lang = language if language in LANGUAGES else "en"
    return _STOPPED[lang]


def voice_sent_text(language: str = "en") -> str:
    lang = language if language in LANGUAGES else "en"
    return _VOICE_SENT[lang]


def format_alert(
    district: dict,
    hazards: list[dict],
    anomalies: list[dict],
    language: str = "en",
) -> str:
    """Compact proactive alert: highest hazard + anomalies + actions, grounded."""
    lang = language if language in LANGUAGES else "en"
    lines = [_ALERT_HEADER[lang].format(
        district=district["name_" + _name_key(lang)], state=district["state"]
    )]
    for h in hazards:
        label = LABELS[lang].get(h["hazard"], h["hazard"])
        band_label = LABELS[lang].get(h["band"], h["band"])
        emoji = HAZARD_EMOJI.get(h["hazard"], "⚠️")
        peak = (h.get("detail") or {}).get("peak_day")
        when = f" (peak {peak})" if peak else ""
        lines.append(f"{emoji} {label}: {band_label} ({h['score']:.0f}/100){when}")
        for action in h.get("actions", []):
            lines.append(f"   ➜ {action}")
    for e in anomalies:
        lines.append(f"⚠️ {e['message']}")
    lines.append(_SOURCES_LINE)
    return "\n".join(lines)

_DEVANAGARI = re.compile(r"[\u0900-\u097F]")
_MR_HINTS = ("आहे", "आहेत", "नका", "काय", "तुम्ही", "माझा", "पाणी", "कशी", "किती", "हवी", "उदा.")


def detect_language(text: str, default: str = "en") -> str:
    """Detect en/hi/mr. Devanagari script + Marathi markers => mr, else hi."""
    if not _DEVANAGARI.search(text or ""):
        return default
    if any(h in text for h in _MR_HINTS):
        return "mr"
    return "hi"


def playbook_actions(hazard: str, band: str, language: str) -> list[str]:
    """Do's & don'ts for a hazard+severity from the curated NDMA-style playbook."""
    haz = _PLAYBOOKS["hazards"].get(hazard)
    if not haz:
        return []
    band = band if band in ("low", "moderate", "high") else "moderate"
    lang = language if language in LANGUAGES else "en"
    return list(haz.get(band, {}).get(lang, haz.get(band, {}).get("en", [])))


def format_advisory(
    district: dict,
    hazards: list[dict],
    language: str = "en",
    include_actions: bool = True,
) -> str:
    """Deterministic, grounded advisory text (works with zero LLM)."""
    lang = language if language in LANGUAGES else "en"
    lines = [_INTRO[lang].format(district=district["name_" + _name_key(lang)], state=district["state"])]
    for h in hazards:
        label = LABELS[lang].get(h["hazard"], h["hazard"])
        band_label = LABELS[lang].get(h["band"], h["band"])
        emoji = HAZARD_EMOJI.get(h["hazard"], "⚠️")
        if h.get("score") is None:
            lines.append(f"{emoji} {label}: {LABELS[lang]['unknown']}")
            continue
        lines.append(f"{emoji} {label}: {band_label} ({h['score']:.0f}/100)")
        for key, val in (h.get("detail") or {}).items():
            lines.append(f"   • {key}: {val}")
        if include_actions:
            for action in h.get("actions", []):
                lines.append(f"   ➜ {action}")
    lines.append(_SOURCES_LINE)
    return "\n".join(lines)


def format_forecast(district: dict, rows: list[dict], language: str = "en") -> str:
    lang = language if language in LANGUAGES else "en"
    header = _FORECAST_HEADER[lang].format(district=district["name_" + _name_key(lang)], n=max(len(rows), 7))
    if not rows:
        return header + "\n" + _NO_FORECAST[lang]
    lines = [header]
    for r in rows:
        rain = r.get("precipitation")
        rain_s = f"{rain:.0f}mm" if rain is not None else "-"
        t = r.get("tavg")
        t_s = f"{t:.0f}°C" if t is not None else "-"
        lines.append(f"   • {r['day']}: {t_s}, {rain_s}")
    return "\n".join(lines)


def ask_which_district(language: str = "en") -> str:
    return _ASK_DISTRICT[language if language in LANGUAGES else "en"]


def _name_key(lang: str) -> str:
    return {"hi": "hi", "mr": "mr"}.get(lang, "en")
