"""Voice + WhatsApp webhook parsing tests."""

import io
import wave

from suraksha.delivery.voice import _silent_wav, synthesize
from suraksha.delivery.whatsapp import extract_webhook_event


def test_silent_wav_is_valid_audio():
    audio = _silent_wav("This is a test advisory with twelve words exactly here.", seconds_per_10_words=1.0)
    assert len(audio) > 1000
    wf = wave.open(io.BytesIO(audio), "rb")
    assert wf.getnchannels() == 1
    assert wf.getframerate() == 16000
    assert wf.getnframes() > 8000  # ~0.5s at least for this text length


def test_synthesize_offline_returns_wav():
    async def run():
        data, is_tts = await synthesize("नमस्ते, यह एक परीक्षण है।", "hi")
        return data, is_tts

    import asyncio

    data, is_tts = asyncio.run(run())
    # edge-tts may or may not be installed/networked; both outcomes must be valid
    if is_tts:
        assert len(data) > 1000
    else:
        wf = wave.open(io.BytesIO(data), "rb")
        assert wf.getnframes() > 0


def test_extract_webhook_text_message():
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {"type": "text", "from": "919876543210", "timestamp": "1", "text": {"body": "Pune advisory"}}
                            ]
                        }
                    }
                ]
            }
        ]
    }
    event = extract_webhook_event(payload)
    assert event == {"from": "919876543210", "text": "Pune advisory", "timestamp": "1"}


def test_extract_webhook_ignores_status_updates():
    assert extract_webhook_event({"entry": [{"changes": [{"value": {"statuses": []}}]}]}) is None
