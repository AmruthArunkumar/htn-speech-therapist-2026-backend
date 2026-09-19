"""Orchestrates transcribe -> measure -> coach -> (optionally) speak."""

import base64
import time
from contextlib import contextmanager

import anyio

from database.config import get_settings
from speech import coach, metrics, stt, tts
from speech.schemas import SpeechAnalysisResponse

MIN_DURATION_S = 1.0
MIN_WORDS = 3


class AudioTooShort(ValueError):
    """Not enough speech to measure anything meaningful."""


class AudioTooLong(ValueError):
    """Clip exceeds the configured practice length."""


class AudioUnrecognized(ValueError):
    """Scribe returned no words."""


@contextmanager
def _timed(timings: dict[str, int], key: str):
    started = time.perf_counter()
    try:
        yield
    finally:
        timings[key] = int((time.perf_counter() - started) * 1000)


async def analyze_speech(
    audio: bytes,
    filename: str,
    context: str | None = None,
    speak: bool = False,
) -> SpeechAnalysisResponse:
    """Run one clip through the full coaching pipeline.

    The provider SDKs are blocking, so each call is pushed to a worker thread to
    keep the event loop free for other requests.
    """
    timings: dict[str, int] = {}

    with _timed(timings, "stt"):
        transcript, words = await anyio.to_thread.run_sync(
            stt.transcribe, audio, filename
        )

    with _timed(timings, "metrics"):
        measured = metrics.analyze(words, transcript)

    if not transcript.strip() or measured.word_count == 0:
        raise AudioUnrecognized("no speech detected")
    if measured.word_count < MIN_WORDS or measured.duration_s < MIN_DURATION_S:
        raise AudioTooShort(
            f"{measured.word_count} words in {measured.duration_s}s"
        )
    max_seconds = get_settings().max_audio_seconds
    if measured.duration_s > max_seconds:
        raise AudioTooLong(f"{measured.duration_s}s exceeds {max_seconds}s")

    with _timed(timings, "coach"):
        feedback = await anyio.to_thread.run_sync(
            coach.generate_feedback, transcript, measured, context
        )

    audio_base64 = None
    if speak:
        with _timed(timings, "tts"):
            spoken = await anyio.to_thread.run_sync(
                tts.synthesize, feedback.coaching_cue
            )
        if spoken:
            audio_base64 = base64.b64encode(spoken).decode()

    return SpeechAnalysisResponse(
        transcript=transcript,
        metrics=measured,
        feedback=feedback,
        audio_base64=audio_base64,
        timings_ms=timings,
    )
