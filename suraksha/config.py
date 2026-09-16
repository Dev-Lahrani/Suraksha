"""Central configuration loaded from environment / .env file."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Storage
    database_url: str = "sqlite:///data/suraksha.db"

    # LLM agent (Nugen = sponsor; any OpenAI-compatible endpoint works)
    nugen_api_key: str = ""
    nugen_base_url: str = "https://api.nugen.xyz/v1"
    nugen_model: str = "nugen-flash-llm"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"

    # WhatsApp Cloud API
    whatsapp_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: str = "suraksha-verify"

    # Voice (edge-tts voices; empty disables TTS)
    tts_voice_hi: str = "hi-IN-MadhurNeural"
    tts_voice_mr: str = "mr-IN-AarohiNeural"
    tts_voice_en: str = "en-IN-NeerjaNeural"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    ingest_interval_minutes: int = 60


@lru_cache
def get_settings() -> Settings:
    return Settings()
