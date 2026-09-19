"""Optional ElevenLabs synthesis of the spoken coaching cue."""

import logging

from database.config import get_settings
from speech.elevenlabs_client import get_client

logger = logging.getLogger(__name__)


def synthesize(text: str) -> bytes | None:
    """Render the cue as mp3. Returns None on failure - voice is never required."""
    settings = get_settings()
    try:
        stream = get_client().text_to_speech.convert(
            voice_id=settings.elevenlabs_voice_id,
            model_id=settings.elevenlabs_tts_model,
            text=text,
            output_format="mp3_44100_128",
        )
        return b"".join(stream)
    except Exception:  # noqa: BLE001 - optional extra, degrade quietly
        logger.exception("TTS synthesis failed")
        return None
