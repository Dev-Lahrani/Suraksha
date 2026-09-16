"""Voice advisory synthesis (edge-tts primary; deterministic offline fallback).

The fallback writes a real (silent) WAV so the demo pipeline always produces a
playable voice note even with no network — success flag tells callers which
path produced the audio.
"""

from __future__ import annotations

import io
import logging
import math
import struct
import wave

from suraksha.config import get_settings

logger = logging.getLogger(__name__)


async def synthesize(text: str, language: str = "en") -> tuple[bytes, bool]:
    """Return (audio_bytes, is_real_tts). Never raises."""
    voice = _voice_for(language)
    if voice:
        try:
            import edge_tts  # optional dependency

            communicate = edge_tts.Communicate(text, voice)
            buf = io.BytesIO()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    buf.write(chunk["data"])
            data = buf.getvalue()
            if data:
                return data, True
        except Exception as exc:  # noqa: BLE001
            logger.warning("edge-tts failed (%s); using offline WAV fallback", exc)
    return _silent_wav(text), False


def _voice_for(language: str) -> str:
    s = get_settings()
    return {
        "hi": s.tts_voice_hi,
        "mr": s.tts_voice_mr,
        "en": s.tts_voice_en,
    }.get(language, "")


def _silent_wav(text: str, seconds_per_10_words: float = 4.0) -> bytes:
    """Generate a low-amplitude WAV sized to the text length (demo fallback)."""
    words = max(1, len(text.split()))
    seconds = min(30.0, seconds_per_10_words * words / 10.0)
    rate = 16000
    n = int(rate * seconds)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        frames = bytearray()
        for i in range(n):
            frames += struct.pack("<h", int(40 * math.sin(2 * math.pi * 110 * i / rate)))
        wav.writeframes(bytes(frames))
    return buf.getvalue()
