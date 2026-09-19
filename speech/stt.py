"""ElevenLabs Scribe transcription. The only place the STT call lives."""

from io import BytesIO

from database.config import get_settings
from speech.elevenlabs_client import get_client
from speech.schemas import WordTiming


class SttUnavailable(RuntimeError):
    """Transcription provider failed. Maps to ASSESSMENT_UNAVAILABLE."""


def transcribe(audio: bytes, filename: str) -> tuple[str, list[WordTiming]]:
    """Transcribe one clip into text plus word-level timings.

    ``no_verbatim`` is deliberately left off: it strips exactly the fillers and
    false starts the analyser exists to measure.
    """
    settings = get_settings()
    payload = BytesIO(audio)
    payload.name = filename

    try:
        result = get_client().speech_to_text.convert(
            file=payload,
            model_id=settings.elevenlabs_stt_model,
            language_code="eng",
            timestamps_granularity="word",
            tag_audio_events=True,
            diarize=False,
        )
    except Exception as exc:  # noqa: BLE001 - provider errors are opaque
        raise SttUnavailable(str(exc)) from exc

    words = [
        WordTiming(
            text=word.text,
            start=getattr(word, "start", None),
            end=getattr(word, "end", None),
            type=getattr(word, "type", None) or "word",
        )
        for word in (getattr(result, "words", None) or [])
    ]

    return getattr(result, "text", "") or "", words
