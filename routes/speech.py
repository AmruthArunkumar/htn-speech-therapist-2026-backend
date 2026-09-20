"""Speech analysis endpoint - the surface the Expo app calls."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status

from speech.pipeline import (
    AudioTooLong,
    AudioTooShort,
    AudioUnrecognized,
    analyze_speech,
)
from speech.schemas import SpeechAnalysisResponse
from speech.stt import SttUnavailable

# Safety net against absurd uploads; the real limit is settings.max_audio_seconds,
# enforced on the decoded duration after transcription.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

router = APIRouter(prefix="/api/v1/speech", tags=["speech"])


def _error(code: str, message: str, http_status: int) -> HTTPException:
    return HTTPException(
        status_code=http_status, detail={"code": code, "message": message}
    )


# TODO: require auth (CurrentUser) once attempts are persisted per user.
@router.post("/analyze", response_model=SpeechAnalysisResponse)
async def analyze(
    audio: UploadFile = File(...),
    context: str | None = Form(None),
    speak: bool = Query(False, description="Also return the cue as synthesized mp3"),
) -> SpeechAnalysisResponse:
    """Transcribe a clip, measure how it was spoken, and return coaching."""
    payload = await audio.read()

    if not payload:
        raise _error(
            "AUDIO_TOO_SHORT", "No audio received.", status.HTTP_422_UNPROCESSABLE_ENTITY
        )
    if len(payload) > MAX_UPLOAD_BYTES:
        raise _error(
            "AUDIO_TOO_LONG",
            f"Upload exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)}MB.",
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )

    try:
        return await analyze_speech(
            audio=payload,
            filename=audio.filename or "recording.wav",
            context=context,
            speak=speak,
        )
    except AudioTooShort as exc:
        raise _error(
            "AUDIO_TOO_SHORT",
            f"Not enough speech to analyse ({exc}). Try speaking for a few seconds.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        ) from exc
    except AudioTooLong as exc:
        raise _error(
            "AUDIO_TOO_LONG",
            f"Recording is too long ({exc}).",
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        ) from exc
    except AudioUnrecognized as exc:
        raise _error(
            "AUDIO_UNRECOGNIZED",
            "No speech was detected in that recording.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        ) from exc
    except SttUnavailable as exc:
        raise _error(
            "ASSESSMENT_UNAVAILABLE",
            "Transcription is temporarily unavailable.",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc
