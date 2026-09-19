"""Shared ElevenLabs client, built once and reused by STT and TTS."""

from functools import lru_cache

from elevenlabs.client import ElevenLabs

from database.config import get_settings


@lru_cache
def get_client() -> ElevenLabs:
    return ElevenLabs(api_key=get_settings().elevenlabs_api_key)
