"""Chat brain tests (offline: deterministic template replies)."""

from suraksha.agent.brain import handle_message


async def test_english_flood_question():
    reply = await handle_message("t1", "Is there flood risk in Pune this week?")
    assert "Pune" in reply
    assert "Suraksha advisory" in reply


async def test_hindi_question_gets_hindi_reply():
    reply = await handle_message("t2", "पुणे में गर्मी का खतरा क्या है?")
    assert "सुरक्षा सलाह" in reply


async def test_marathi_question_gets_marathi_reply():
    reply = await handle_message("t3", "पुण्यात पावसाचा धोका आहे का?")
    assert "सुरक्षा सलाह" in reply


async def test_unknown_district_asks_back():
    reply = await handle_message("t4", "What about Atlantis?")
    assert "district" in reply.lower() or "जिल" in reply or "जिल्ह्याची" in reply


async def test_session_remembers_district():
    await handle_message("t5", "Pune advisory")
    reply = await handle_message("t5", "What about tomorrow?")
    assert "Pune" in reply or "पुणे" in reply


async def test_forecast_intent():
    await handle_message("t6", "Pune")
    reply = await handle_message("t6", "Show me the forecast")
    assert "Pune" in reply
