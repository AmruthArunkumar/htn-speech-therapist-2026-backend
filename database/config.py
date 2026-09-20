from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    mongodb_url: str
    mongodb_database: str
    jwt_secret_key: str
    jwt_algorithm: str
    access_token_expire_minutes: int
    elevenlabs_api_key: str
    elevenlabs_stt_model: str = "scribe_v2"
    elevenlabs_tts_model: str = "eleven_flash_v2_5"
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"
    gemini_api_key: str
    gemini_model: str = "gemini-3.8-flash"
    gemini_fallback_model: str = "gemini-3.5-flash"
    # 0 disables reasoning tokens: ~2.5x faster, and the coach is summarising
    # facts it was handed rather than solving anything. Raise to trade latency
    # for more careful focus selection.
    gemini_thinking_budget: int = 0
    # Flash capacity is shared and spiky: 429/503 show up on a few percent of
    # calls and clear within a second or two. Retry the same model before
    # downgrading to the fallback. Worst case adds ~3.5s before we give up on
    # the primary, which still fits inside a coaching turn.
    gemini_retry_attempts: int = 3
    gemini_retry_initial_delay: float = 0.5
    gemini_retry_max_delay: float = 4.0
    gemini_timeout_s: float = 30.0
    max_audio_seconds: int = 120

    # Practice clips are stored in S3; Mongo keeps only the object key.
    # Leave s3_bucket empty to run without AWS - uploads are skipped and
    # reviews save with audio=None, so local dev needs no credentials.
    s3_bucket: str = ""
    s3_region: str = "us-east-1"
    s3_key_prefix: str = "speech-attempts"
    # Blank falls back to boto3's own chain (instance/task role, ~/.aws,
    # AWS_* vars), which is what you want anywhere but a laptop.
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    # Playback URLs are signed per request. Long enough to start playing,
    # short enough that a leaked link dies quickly.
    s3_url_expiry_s: int = 3600

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()