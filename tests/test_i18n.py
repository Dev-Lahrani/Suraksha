"""i18n tests: detection, playbooks, deterministic formatting."""

from suraksha.agent.i18n import (
    ask_which_district,
    detect_language,
    format_advisory,
    format_forecast,
    playbook_actions,
)


def test_detect_english():
    assert detect_language("Is there flood risk in Pune?") == "en"


def test_detect_hindi():
    assert detect_language("क्या अगले 5 दिन में नागपुर में बाढ़ का खतरा है?") == "hi"


def test_detect_marathi():
    # Marathi marker word "आहे" distinguishes from Hindi
    assert detect_language("पुण्यात पावसाचा धोका आहे का?") == "mr"


def test_detect_tamil():
    assert detect_language("மேற்கு மாநிலம் புணேயில் வெப்பம் ஆபத்து உள்ளப்படியா?") == "ta"


def test_detect_telugu():
    assert detect_language("ప్రశ్ఞ: ఈస్ట్ రాష్ట్రంలోని పునేలో వేడి ప్రమాదం ఉందా?") == "te"


def test_detect_kannada():
    assert detect_language("ಪ್ರಶ್ನೆ: ಪೂರ್ವ ರಾಜ್ಯದಲ್ಲಿನ ಪುಣೇದಲ್ಲಿ ಉಷ್ಣತೆ ಅಪಾಯವಿದೆಯೋ?") == "kn"


def test_detect_bengali():
    assert detect_language("প্রশ্ন: পূর্ব রাজ্যে পুনে সূর্যতাপ ঝুঁকি আছে কি?") == "bn"


def test_playbook_localised():
    hi = playbook_actions("heat", "high", "hi")
    assert hi and "आपातकाल" in hi[0]
    mr = playbook_actions("heat", "high", "mr")
    assert mr and "आपत्कालीन" in mr[0]
    en = playbook_actions("heat", "high", "en")
    assert en and "EMERGENCY" in en[0]


def test_playbook_localised_tamil():
    ta = playbook_actions("heat", "high", "ta")
    assert ta and "அவசியப்பட்ட" in ta[0]


def test_playbook_localised_telugu():
    te = playbook_actions("flood", "high", "te")
    assert te and "అవసరమైన" in te[0]


def test_playbook_localised_kannada():
    kn = playbook_actions("air", "high", "kn")
    assert kn and "ಅವಶ್ಯಕರವಲ್ಲದೆ" in kn[0]


def test_playbook_localised_bengali():
    bn = playbook_actions("heat", "low", "bn")
    assert bn and "পর্যাপ্ত" in bn[0]


def test_format_advisory_tamil():
    district = {
        "name_en": "Chennai",
        "name_ta": "சென்னை",
        "state": "Tamil Nadu",
    }
    hazards = [
        {
            "hazard": "heat",
            "score": 80.0,
            "band": "high",
            "detail": {"heat_index_c": 48.5},
            "actions": playbook_actions("heat", "high", "ta"),
        }
    ]
    text = format_advisory(district, hazards, "ta")
    assert "சென்னை" in text
    assert "வெப்பம்" in text
    assert "அதிக" in text


def test_playbook_invalid_band_falls_back():
    actions = playbook_actions("flood", "bogus", "en")
    assert actions  # falls back to moderate


def test_format_advisory_hindi():
    district = {
        "name_en": "Pune",
        "name_hi": "पुणे",
        "name_mr": "पुणे",
        "state": "Maharashtra",
    }
    hazards = [
        {
            "hazard": "heat",
            "score": 70.0,
            "band": "high",
            "detail": {"heat_index_c": 47.2},
            "actions": playbook_actions("heat", "high", "hi"),
        }
    ]
    text = format_advisory(district, hazards, "hi")
    assert "पुणे" in text
    assert "गर्मी" in text
    assert "उच्च" in text
    assert "➜" in text
    assert "Open-Meteo" in text  # sources line always present


def test_format_forecast_empty_shows_message():
    district = {"name_en": "Pune", "name_hi": "पुणे", "name_mr": "पुणे", "state": "MH"}
    text = format_forecast(district, [], "hi")
    assert "अनुमान" in text


def test_format_forecast_rows():
    district = {"name_en": "Pune", "name_hi": "पुणे", "name_mr": "पुणे", "state": "MH"}
    rows = [
        {"day": "2026-10-01", "tavg": 27.3, "precipitation": 12.0},
        {"day": "2026-10-02", "tavg": 28.1, "precipitation": 0.0},
    ]
    text = format_forecast(district, rows, "en")
    assert "2026-10-01" in text and "12mm" in text


def test_ask_district_localised():
    assert "district" in ask_which_district("en").lower()
    assert "ज़िले" in ask_which_district("hi")
    assert "மாவட" in ask_which_district("ta")  # word appears in 'மாவட்டத்துக்கு'
    assert "జిల్లా" in ask_which_district("te")
    assert "ಜಿಲ್ಲೆ" in ask_which_district("kn")
    assert "জেল" in ask_which_district("bn")  # 'জেল্যার' has root 'জেল'
