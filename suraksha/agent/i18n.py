"""i18n: playbooks, language detection and multilingual text formatting."""

from __future__ import annotations

import json
import re
from pathlib import Path

RESOURCES = Path(__file__).resolve().parents[2] / "resources"
_PLAYBOOKS = json.loads((RESOURCES / "playbooks.json").read_text(encoding="utf-8"))

_EXTRA = json.loads((RESOURCES / "languages.json").read_text(encoding="utf-8"))
LANGUAGES = ("en", "hi", "mr", "ta", "te", "kn", "bn", *_EXTRA)


def language_catalog() -> list[dict]:
    names = {"en": "English", "hi": "हिन्दी", "mr": "मराठी", "ta": "தமிழ்", "te": "తెలుగు", "kn": "ಕನ್ನಡ", "bn": "বাংলা"}
    return [dict(code=code, name=names.get(code, _EXTRA.get(code, {}).get("name")),
                 locale=_EXTRA.get(code, {}).get("locale", f"{code}-IN"),
                 direction="rtl" if code == "ur" else "ltr",
                 experimental=code not in ("en", "hi", "mr")) for code in LANGUAGES]

LABELS: dict[str, dict[str, str]] = {
    "en": {"heat": "Heat", "flood": "Flood", "air": "Air quality", "low": "Low", "moderate": "Moderate", "high": "High", "unknown": "Unknown"},
    "hi": {"heat": "गर्मी", "flood": "बाढ़", "air": "वायु गुणवत्ता", "low": "कम", "moderate": "मध्यम", "high": "उच्च", "unknown": "अज्ञात"},
    "mr": {"heat": "उष्मा", "flood": "पूर", "air": "हवेची गुणवत्ता", "low": "कमी", "moderate": "मध्यम", "high": "उच्च", "unknown": "अज्ञात"},
    "ta": {"heat": "வெப்பம்", "flood": "வெள்ளம்", "air": "காற்றின் தரம்", "low": "குறைந்த", "moderate": "இடுநிலை", "high": "உயர்", "unknown": "தெரியாது"},
    "te": {"heat": "వేడి", "flood": "వరద", "air": "గాలి నాణ్యత", "low": "తక్కువ", "moderate": "మధ్యమ", "high": "ఎక్కువ", "unknown": "తెలియదు"},
    "kn": {"heat": "ಉಷ್ಣ", "flood": "ಪ್ರವಾಹ", "air": "ಗಾಳಿಯ ಗುಣಮಟ್ಟ", "low": "ಕಡಿಮೆ", "moderate": "ಮಧ್ಯಮ", "high": "ಹೆಚ್ಚು", "unknown": "ಗೊತ್ತಿಲಿ"},
    "bn": {"heat": "তাপ", "flood": "বন্যা", "air": "হাওয়ার গুণগত মান", "low": "নিম্ন", "moderate": "মাঝারি", "high": "উচ্চ", "unknown": "অজানা"},
}

DISTRICT_ALIASES = {
    "gu": {"પુણે": "PUNE", "અમદાવાદ": "AHMEDABAD", "દિલ્હી": "DELHI_NW", "કચ્છ": "KUTCH"},
    "pa": {"ਪੁਣੇ": "PUNE", "ਦਿੱਲੀ": "DELHI_NW", "ਚੰਡੀਗੜ੍ਹ": "CHANDIGARH", "ਅਹਿਮਦਾਬਾਦ": "AHMEDABAD"},
    "ml": {"പുണെ": "PUNE", "തിരുവനന്തപുരം": "THIRUVANANTHAPURAM", "വയനാട്": "WAYANAD", "എറണാകുളം": "ERNAKULAM"},
    "ur": {"پونے": "PUNE", "دہلی": "DELHI_NW", "حیدرآباد": "HYDERABAD", "احمد آباد": "AHMEDABAD"},
}

HAZARD_EMOJI = {"heat": "🔥", "flood": "🌊", "air": "😷"}

_INTRO: dict[str, str] = {
    "en": "🛡️ Suraksha advisory for {district} ({state})",
    "hi": "🛡️ सुरक्षा सलाह — {district} ({state})",
    "mr": "🛡️ सुरक्षा सलाह — {district} ({state})",
    "ta": "🛡️ சுரக்ஷா ஆலோசனை — {district} ({state})",
    "te": "🛡️ సురక్షా సలహాలు — {district} ({state})",
    "kn": "🛡️ ಸುರಕ್ಷ ಮಾರ್ಗಸೂಚಿ — {district} ({state})",
    "bn": "🛡️ সুরক্ষা পরামর্শ — {district} ({state})",
}

_ASK_DISTRICT: dict[str, str] = {
    "en": "Which district do you want the advisory for? e.g. 'Pune', 'Delhi', 'Wayanad'.",
    "hi": "किस ज़िले की सलाह चाहिए? जैसे 'पुणे', 'दिल्ली', 'वायनाड'।",
    "mr": "कोणत्या जिल्ह्याची सलाह हवी? उदा. 'पुणे', 'दिल्ली', 'वायनाड'.",
    "ta": "எந்த மாவட்டத்துக்கு ஆலோசனை தேவை? உதாரணம்: 'புணே', 'டெல்லி', 'வாயனாட்'.",
    "te": "ఏ జిల్లా సలహాలు కావాలి? ఉదాహరణకి: 'పునే', 'ఢిల్లీ', 'వాయనాడ్'.",
    "kn": "ಯಾವುದು ಜಿಲ್ಲೆಯ ಮಾರ್ಗಸೂಚಿಗೆ ಅವಶ್ಯಕ? ಉದಾ: 'ಪುಣೇ', 'ಡೆಲ್ಲಿ', 'ವಾಯನಾಡ್'.",
    "bn": "কোন জেল্যার পরামর্শ দরকার? যেমন 'পুনে', 'ঢিল্লি', 'ভায়ানাড'.",
}

_FORECAST_HEADER: dict[str, str] = {
    "en": "🗓️ {district} — next {n} days:",
    "hi": "🗓️ {district} — अगले {n} दिन:",
    "mr": "🗓️ {district} — पुढील {n} दिवस:",
    "ta": "🗓️ {district} — அடுத்த {n} நாட்கள்:",
    "te": "🗓️ {district} — తదుపై {n} రోజులు:",
    "kn": "🗓️ {district} — ಮುಂದಿನ {n} ದಿನಗಳು:",
    "bn": "🗓️ {district} — পরবর্তী {n} দিন:",
}

_NO_FORECAST: dict[str, str] = {
    "en": "No forecast data yet. The pipeline ingests Open-Meteo every hour — try again soon.",
    "hi": "अनुमान डेटा अभी उपलब्ध नहीं है। पाइपलाइन हर घंटे डेटा लाती है — थोड़ी देर बाद कोशिश करें।",
    "mr": "अंदाज डेटा अजून उपलब्ध नाही. पाइपलाइन दर तासाला डेटा आणते — थोड्या वेळाने प्रयत्न करा.",
    "ta": "முன்கூத்டிய தரவு இன்னும் கிடைக்கவில்லை. தொழில்நுட்பம் ஒவ்வொரு மணிக்கு Open-Meteo ஐப் புகுத்துகிறது — இனி சுற்றித்துள்ளம் முயங்கவும்.",
    "te": "ముందస్టి డేటా లేదు. పైప్లైన్ ప్రతి గంట Open-Meteo ని నిండిస్తుంది — స్వల్ప సమయంలో మళ్లీ ప్రయత్నించండి.",
    "kn": "ಮುಂದಿನ ಡೇಟಾ ಇನ್ನು ಲಭ್ಯವಾಗಿಲ್ಲ. ಪೈಪ್ಲೈನ್ ಪ್ರತಿ ಗಂಟೆ Open-Meteo ಅನ್ನು ಸೇರಿಸುತ್ತದೆ — ಸ್ವಲ್ಪ ಸಮಯ ಕಾಲಿಗೆ ಪ್ರಯತ್ನಿಸಿ.",
    "bn": "এখানে এখনো কোনও আগাম ডেটা নেই। পাইপলাইন প্রতি ঘন্টায় Open-Meteo আনে — একটু সময় পরে আবার চেষ্টা করুন।",
}

_SUBSCRIBED: dict[str, str] = {
    "en": "✅ Subscribed! You will get a Suraksha alert for {district} when risk turns high or something unusual happens.\nSend 'STOP' anytime to unsubscribe.",
    "hi": "✅ सदस्यता ली गई! जब {district} में खतरा अधिक होगा या कुछ असामान्य होगा, तो आपको सुरक्षा अलर्ट मिलेगा।\nसदस्यता रद्द करने के लिए कभी भी 'STOP' भेजें।",
    "mr": "✅ सदस्यता घेतली! {district} मध्ये धोका जास्त असेल का सामान्य नसलेले काही घडले तर तुम्हाला सुरक्षा अलर्ट मिळेल.\nसदस्यता रद्द करण्यासाठी कधीही 'STOP' पाठवा.",
    "ta": "✅ பதிவு செய்யப்பட்டார்கள்! {district} இல் இன்னிமையில் அபான இருக�ையாக அல்லது ஏதாவது தனி சிறப்பமைஞ் நிகழவில் நீங்கள் சுரக்ஷா எச்சரிக்கையைப் பெறு஬ீர்கள். \nபதிவை ரதிகரிக்க 'STOP' ஐ எப்போதும் அனுப்புங்கள்.",
    "te": "✅ సభ్యత్వం లభించింది! {district} లో ప్రమాదం ఎక్కుతనం లేదా ఏదైనా అసాధారణ సంఘటనం జరిగితే మీరు ఒక Suraksha హెచ్చరికను పొందుతారు. \nఏ సమయంలోనైనా 'STOP' ని పంపించి సభ్యత్వాన్ని రద్దు చేయండి.",
    "kn": "✅ ಸಭ್ಯತ್ವ ಪಡೆದಿದೆ! {district} ನಲ್ಲಿ ಅಪಾಯ ಹೆಚ್ಚಿದಾಗ ಅಥವಾ ಯಾವುದಾದರೂ ಅಸಾಮಾನ್ಯ ಸಂಗತಿ ನಿರ್ಮಾಣವಾದಾಗ ನಿಮಗೆ ಒಂದು ಸುರಕ್ಷ ಎಚ್ಚರಿಕೆ ಸಿಕ್ಕುತ್ತದೆ. \nಏನೂ ಸಮಯದಲ್ಲಿ 'STOP' ಅನ್ನು ಕಳುಶಿಯಲು ಸಭ್ಯತ್ವವನ್ನು ರದ್ದು ಮಾಡಿ.",
    "bn": "✅ অ্যালাইন্মেন্ট লাভ করেছে! {district} এ যখন কোনও ঝুঁকি বাড়বে বা কোনও অস্বাভাবিক ঘটনা ঘটলে আপনি একটি Suraksha সতর্কতা পেয়ে যাবেন। \nযেকোনো সময় 'STOP' পাঠিয়ে অ্যালাইন্মেন্ট বাতিল করুন।",
}

_STOPPED: dict[str, str] = {
    "en": "✅ Unsubscribed. You will not receive any more Suraksha alerts.\nSend 'SUBSCRIBE <district>' anytime to rejoin.",
    "hi": "✅ सदस्यता रद्द कर दी गई। अब आपको कोई सुरक्षा अलर्ट नहीं मिलेगा।\nदोबारा जुड़ने के लिए कभी भी 'SUBSCRIBE <ज़िला>' भेजें।",
    "mr": "✅ सदस्यता रद्द केली. आता तुम्हाला सुरक्षा अलर्ट मिळणार नाही.\nपुन्हा सामील होण्यासाठी कधीही 'SUBSCRIBE <जिल्हा>' पाठवा.",
    "ta": "✅ பதிவு ரதிகரிக்கப்பட்டது. இனி நீங்கள் எந்த Suraksha எச்சரிக்கைகளும் பெறாதீர்க்க. \nமீண்டும் இணைய STOP 'SUBSCRIBE <மாவட்டம்>' ஐ எப்போதும் அனுப்புங்கள்.",
    "te": "✅ సభ్యత్వం రద్దు చేయబడింది. మీరు మళ్లీ Suraksha హెచ్చరికలను పొందము. \nతిరిగి చేరడానికి ఏ సమయంలోనైనా 'SUBSCRIBE <జిల్లా>' ని పంపండి.",
    "kn": "✅ ಸಭ್ಯತ್ವವನ್ನು ರದ್ದು ಮಾಡಲಾಗಿದೆ. ನಿಮ್ಮು ಮತ್ತೆ Suraksha ಎಚ್ಚರಿಕೆಗಳನ್ನು ಪಡೆಯುವುದಿಲ್ಲ. \nಪುನಃಸ್ವೀಕರಿಸಲು ಯಾವಾಗಲೂ 'SUBSCRIBE <ಜಿಲ್ಲೆ>' ಅನ್ನು ಕಳುಶಿಯಿರಿ.",
    "bn": "✅ অ্যালাইন্মেন্ট বাতিল করা হয়েছে। আপনি কোনও Suraksha সতর্কতা আর পাবেন না। \nআবার যুক্ত হতে 'SUBSCRIBE <জেলা>' পাঠিয়ে নিন।",
}

_VOICE_SENT: dict[str, str] = {
    "en": "🎧 Advisory sent as a voice note.",
    "hi": "🎧 सलाह वॉयस नोट के रूप में भेज दी गई है।",
    "mr": "🎧 सलाह व्हॉइस नोट म्हणून पाठवली आहे.",
    "ta": "🎧 ஆலோசனை ஒலி குறிப்பாக அனுப்பப்பட்டது.",
    "te": "🎧 సలహా ఆడియో గమనికగా పంపబడింది.",
    "kn": "🎧 ಮಾರ್ಗಸೂಚಿ ಆವಾಜ್ ಗಮನಿಯಾಗಿ ಕಳುಶಿಯಲ್ಪಟ್ಟಿದೆ.",
    "bn": "🎧 পরামর্শ ভয়েস নোট হিসাবে পাঠানো হয়েছে।",
}

_ALERT_HEADER: dict[str, str] = {
    "en": "🚨 Suraksha alert — {district} ({state})",
    "hi": "🚨 सुरक्षा अलर्ट — {district} ({state})",
    "mr": "🚨 सुरक्षा अलर्ट — {district} ({state})",
    "ta": "🚨 சுரக்ஷா எச்சரிக்கை — {district} ({state})",
    "te": "🚨 సురక్షా హెచ్చరిక — {district} ({state})",
    "kn": "🚨 ಸುರಕ್ಷ ಎಚ್ಚರಿಕೆ — {district} ({state})",
    "bn": "🚨 সুরক্ষা সতর্কতা — {district} ({state})",
}

for _code, _pack in _EXTRA.items():
    LABELS[_code] = _pack["labels"]
    for _mapping, _key in ((_INTRO, "intro"), (_ASK_DISTRICT, "ask"), (_FORECAST_HEADER, "forecast"),
                           (_NO_FORECAST, "no_data"), (_SUBSCRIBED, "subscribed"),
                           (_STOPPED, "stopped"), (_VOICE_SENT, "voice_sent"), (_ALERT_HEADER, "alert")):
        _mapping[_code] = _pack[_key]

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
        district=(district.get("name_" + _name_key(lang)) or district.get("name_en", "")), state=district["state"]
    )]
    if not hazards and not anomalies:
        lines.append(_NO_FORECAST[lang])
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
    from suraksha.config import get_settings
    if get_settings().demo_mode:
        lines.insert(0, "DEMO — synthetic data, not a live warning")
    lines.append(_SOURCES_LINE)
    return "\n".join(lines)

_DEVANAGARI = re.compile(r"[\u0900-\u097F]")
_TAMIL = re.compile(r"[\u0B80-\u0BFF]")
_TELUGU = re.compile(r"[\u0C00-\u0C7F]")
_KANNADA = re.compile(r"[\u0C80-\u0CFF]")
_BENGALI = re.compile(r"[\u0980-\u09FF]")
_MR_HINTS = ("आहे", "आहेत", "नका", "काय", "तुम्ही", "माझा", "पाणी", "कशी", "किती", "हवी", "उदा.")


def detect_language(text: str, default: str = "en") -> str:
    """Detect en/hi/mr/ta/te/kn/bn by Unicode script block.

    Each Indic script maps uniquely to one language: Devanagari→hi/mr,
    Tamil→ta, Telugu→te, Kannada→kn, Bengali→bn. Marathi is distinguished
    from Hindi by the Marathi marker words above within Devanagari.
    """
    if not text:
        return default
    for pattern, code in ((r"[\u0A80-\u0AFF]", "gu"), (r"[\u0A00-\u0A7F]", "pa"),
                          (r"[\u0D00-\u0D7F]", "ml"), (r"[\u0600-\u06FF]", "ur")):
        if re.search(pattern, text):
            return code
    if _DEVANAGARI.search(text):
        if any(h in text for h in _MR_HINTS):
            return "mr"
        return "hi"
    if _TAMIL.search(text):
        return "ta"
    if _TELUGU.search(text):
        return "te"
    if _KANNADA.search(text):
        return "kn"
    if _BENGALI.search(text):
        return "bn"
    return default


def playbook_actions(hazard: str, band: str, language: str) -> list[str]:
    """Do's & don'ts for a hazard+severity from the curated NDMA-style playbook."""
    haz = _PLAYBOOKS["hazards"].get(hazard)
    if not haz:
        return []
    band = band if band in ("low", "moderate", "high") else "moderate"
    lang = language if language in LANGUAGES else "en"
    if lang in _EXTRA:
        return list(_EXTRA[lang]["actions"].get(hazard, {}).get(band, []))
    return list(haz.get(band, {}).get(lang, haz.get(band, {}).get("en", [])))


def format_advisory(
    district: dict,
    hazards: list[dict],
    language: str = "en",
    include_actions: bool = True,
) -> str:
    """Deterministic, grounded advisory text (works with zero LLM)."""
    lang = language if language in LANGUAGES else "en"
    lines = [_INTRO[lang].format(district=(district.get("name_" + _name_key(lang)) or district.get("name_en", "")), state=district["state"])]
    if not hazards:
        lines.append(_NO_FORECAST[lang])
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
    from suraksha.config import get_settings
    if get_settings().demo_mode:
        lines.insert(0, "DEMO — synthetic data, not a live warning")
    lines.append(_SOURCES_LINE)
    return "\n".join(lines)


def format_forecast(district: dict, rows: list[dict], language: str = "en") -> str:
    lang = language if language in LANGUAGES else "en"
    header = _FORECAST_HEADER[lang].format(district=(district.get("name_" + _name_key(lang)) or district.get("name_en", "")), n=len(rows) or 7)
    if not rows:
        return header + "\n" + _NO_FORECAST[lang]
    lines = [header]
    from suraksha.config import get_settings
    if get_settings().demo_mode:
        lines.insert(0, "DEMO — synthetic data, not a live warning")
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
    return {"hi": "hi", "mr": "mr", "ta": "ta", "te": "te", "kn": "kn", "bn": "bn"}.get(lang, "en")
